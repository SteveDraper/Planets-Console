"""Read, write, and invalidate homeworld locator persistence documents."""

from __future__ import annotations

import threading
from dataclasses import replace

from api.analytics.fleet.ledger_persisted_event import FleetAgeIdentityChanged
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.fleet_age_refetch import (
    FLEET_AGE_RETAINED_CHANGES,
    FleetAgeRefetchNotice,
    notice_for_fleet_age_changes,
)
from api.analytics.homeworld_locator.serialization import (
    fleet_age_stale_document_from_json,
    fleet_age_stale_document_to_json,
    homeworld_evidence_aggregate_from_json,
    homeworld_evidence_aggregate_to_json,
    homeworld_locator_game_state_from_json,
    homeworld_locator_game_state_to_json,
)
from api.analytics.homeworld_locator.types import (
    FleetAgeStaleDocument,
    FleetAgeStaleMarker,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
    ensure_candidates_for_asserted_locations,
)
from api.analytics.persistence_paths import (
    game_global_analytic_document_key,
    perspective_analytic_document_key,
    turn_scoped_analytic_document_key,
)
from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend


class HomeworldLocatorPersistenceService:
    """Persist game-global candidates, evidence aggregates, and the fleet-age marker.

    Logical paths (ADR 0002):
    - Game-global: ``games/{gameId}/analytics/homeworld-locator``
    - Evidence: ``games/{gameId}/{perspective}/turns/{turn}/analytics/homeworld-locator``
    - Fleet-age document: ``games/{gameId}/{perspective}/analytics/homeworld-locator``

    The document ``generation`` increments when a roster ledger's build-turn map
    is created, removed, or edited. ``changes`` keeps the last
    ``FLEET_AGE_RETAINED_CHANGES`` ``(generation, turn)`` pairs so a poll can
    name the earliest turn changed after a client epoch. ``staleFromTurn`` is
    the refine frontier. A refine reads ``generation`` before it reads ledger
    stamps and advances ``staleFromTurn`` only when the stored generation is
    still the one it read. A ledger save during refine stays marked. Advancing
    past every stored aggregate clears ``staleFromTurn`` and keeps ``generation``
    and ``changes``.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage
        self._invalidation_generation: dict[tuple[int, int], int] = {}
        self._generation_lock = threading.Lock()
        self._stale_marker_lock = threading.Lock()

    @staticmethod
    def game_global_document_key(game_id: int) -> str:
        return game_global_analytic_document_key(game_id, ANALYTIC_ID)

    @staticmethod
    def evidence_document_key(game_id: int, perspective: int, turn_number: int) -> str:
        return turn_scoped_analytic_document_key(game_id, perspective, turn_number, ANALYTIC_ID)

    @staticmethod
    def fleet_age_stale_marker_key(game_id: int, perspective: int) -> str:
        return perspective_analytic_document_key(game_id, perspective, ANALYTIC_ID)

    def get_game_state(self, game_id: int) -> HomeworldLocatorGameState | None:
        try:
            data = self._storage.get(self.game_global_document_key(game_id))
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("homeworld locator game-global document must be a JSON object")
        return homeworld_locator_game_state_from_json(data)

    def put_game_state(self, game_id: int, state: HomeworldLocatorGameState) -> None:
        self._storage.put(
            self.game_global_document_key(game_id),
            homeworld_locator_game_state_to_json(state),
        )

    def get_evidence_aggregate(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> HomeworldEvidenceAggregate | None:
        try:
            data = self._storage.get(self.evidence_document_key(game_id, perspective, turn_number))
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("homeworld evidence aggregate document must be a JSON object")
        return homeworld_evidence_aggregate_from_json(data)

    def put_evidence_aggregate(
        self,
        game_id: int,
        perspective: int,
        aggregate: HomeworldEvidenceAggregate,
    ) -> None:
        self._storage.put(
            self.evidence_document_key(game_id, perspective, aggregate.turn),
            homeworld_evidence_aggregate_to_json(aggregate),
        )

    def has_baseline_floor(
        self,
        game_id: int,
        perspective: int,
    ) -> bool:
        """True when game-global state and its floor evidence aggregate both exist."""
        state = self.get_game_state(game_id)
        if state is None:
            return False
        floor = self.get_evidence_aggregate(game_id, perspective, state.baseline_turn)
        return floor is not None and floor.baseline_turn == state.baseline_turn

    def put_baseline(
        self,
        game_id: int,
        perspective: int,
        state: HomeworldLocatorGameState,
        floor_aggregate: HomeworldEvidenceAggregate,
    ) -> None:
        if floor_aggregate.turn != state.baseline_turn:
            raise ValidationError(
                "homeworld floor aggregate turn must match game-global baseline_turn"
            )
        if floor_aggregate.baseline_turn != state.baseline_turn:
            raise ValidationError(
                "homeworld floor aggregate baseline_turn must match game-global baseline_turn"
            )
        self.put_game_state(game_id, state)
        self.put_evidence_aggregate(game_id, perspective, floor_aggregate)

    def get_fleet_age_stale_marker(
        self,
        game_id: int,
        perspective: int,
    ) -> FleetAgeStaleMarker | None:
        document = self._read_fleet_age_stale_document(game_id, perspective)
        if document is None:
            return None
        return document.stale_marker()

    def record_fleet_age_identity_changed(
        self,
        event: FleetAgeIdentityChanged,
    ) -> FleetAgeStaleMarker:
        """Mark this perspective stale from ``event.turn`` and append the refetch log.

        ``stale_from_turn`` moves earlier when the event is before the current
        mark and never moves later. A cleared frontier starts again at
        ``event.turn``. ``generation`` increments on every call and does not
        restart when the frontier is cleared.
        """
        if event.turn < 1:
            raise ValidationError("fleet-age stale marker turn must be >= 1")
        with self._stale_marker_lock:
            current = self._read_fleet_age_stale_document(event.game_id, event.perspective)
            generation = 1 if current is None else current.generation + 1
            if current is None or current.stale_from_turn is None:
                stale_from = event.turn
            else:
                stale_from = min(current.stale_from_turn, event.turn)
            prior_changes = () if current is None else current.changes
            updated = FleetAgeStaleDocument(
                generation=generation,
                changes=(prior_changes + ((generation, event.turn),))[-FLEET_AGE_RETAINED_CHANGES:],
                stale_from_turn=stale_from,
            )
            self._write_fleet_age_stale_document(event.game_id, event.perspective, updated)
            return FleetAgeStaleMarker(stale_from_turn=stale_from, generation=generation)

    def advance_fleet_age_stale_marker(
        self,
        game_id: int,
        perspective: int,
        *,
        refined_turn: int,
        observed: FleetAgeStaleMarker | None,
    ) -> None:
        """Move the marker past ``refined_turn`` when ``observed`` still matches.

        ``observed`` is the marker read before this refine read ledger stamps.
        A later identity change bumps ``generation`` and this call leaves the
        marker in place. The frontier also stays put when a stored aggregate
        still sits between the marker and ``refined_turn``. A gap with no
        stored aggregate is contiguous, so the marker moves past ``refined_turn``.
        When that move passes every stored aggregate, ``stale_from_turn`` is
        cleared. ``generation`` and the retained changes stay.
        """
        if observed is None:
            return
        with self._stale_marker_lock:
            current = self._read_fleet_age_stale_document(game_id, perspective)
            marker = None if current is None else current.stale_marker()
            if (
                current is None
                or marker is None
                or marker != observed
                or refined_turn < marker.stale_from_turn
            ):
                return
            if self._has_evidence_aggregate_in_range(
                game_id,
                perspective,
                marker.stale_from_turn,
                refined_turn,
            ):
                return
            next_turn = refined_turn + 1
            if self._has_evidence_aggregate_in_range(game_id, perspective, next_turn, None):
                self._write_fleet_age_stale_document(
                    game_id,
                    perspective,
                    replace(current, stale_from_turn=next_turn),
                )
                return
            self._write_fleet_age_stale_document(
                game_id,
                perspective,
                replace(current, stale_from_turn=None),
            )

    def fleet_age_refetch_notice(
        self,
        game_id: int,
        perspective: int,
        *,
        after_epoch: int,
    ) -> FleetAgeRefetchNotice:
        """Earliest retained identity change with a generation above ``after_epoch``."""
        document = self._read_fleet_age_stale_document(game_id, perspective)
        if document is None:
            return notice_for_fleet_age_changes(0, (), after_epoch=after_epoch)
        return notice_for_fleet_age_changes(
            document.generation,
            document.changes,
            after_epoch=after_epoch,
        )

    def invalidate_inferred_game_state(self, game_id: int) -> HomeworldLocatorGameState | None:
        """Drop inferred game-global candidates; preserve asserted provenances when present."""
        existing = self.get_game_state(game_id)
        if existing is None:
            return None
        has_asserts = bool(
            existing.asserted_location_provenances
            or existing.asserted_sector_ownership
            or existing.asserted_planet_ownership
        )
        if not has_asserts:
            try:
                self._storage.delete(self.game_global_document_key(game_id))
            except NotFoundError:
                pass
            self._bump_generations_for_game(game_id)
            return None
        retained_candidates = ensure_candidates_for_asserted_locations(
            inferred=(),
            asserted_location_provenances=existing.asserted_location_provenances,
        )
        retained = HomeworldLocatorGameState(
            candidates=retained_candidates,
            baseline_turn=existing.baseline_turn,
            baseline_degraded=existing.baseline_degraded,
            settings_fingerprint=(),
            baseline_algorithm_version=existing.baseline_algorithm_version,
            asserted_location_provenances=existing.asserted_location_provenances,
            asserted_sector_ownership=existing.asserted_sector_ownership,
            asserted_planet_ownership=existing.asserted_planet_ownership,
        )
        self.put_game_state(game_id, retained)
        self._bump_generations_for_game(game_id)
        return retained

    def invalidate_evidence_from_turn(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> list[int]:
        """Delete evidence aggregates at turns ``>= turn_number`` (fleet-like)."""
        if turn_number < 1:
            raise ValidationError("turn_number must be >= 1")
        cleared: list[int] = []
        for stored_turn in self._stored_turn_numbers(game_id, perspective):
            if stored_turn < turn_number:
                continue
            key = self.evidence_document_key(game_id, perspective, stored_turn)
            try:
                self._storage.delete(key)
            except NotFoundError:
                continue
            cleared.append(stored_turn)
        if cleared:
            self.bump_invalidation_generation(game_id, perspective)
        return sorted(cleared)

    def clear_baseline_for_recompute(self, game_id: int, perspective: int) -> None:
        """Clear inferred game-global state and all evidence aggregates for one perspective."""
        self.invalidate_inferred_game_state(game_id)
        self.invalidate_evidence_from_turn(game_id, perspective, 1)

    def bump_invalidation_generation(self, game_id: int, perspective: int) -> int:
        with self._generation_lock:
            key = (game_id, perspective)
            next_gen = self._invalidation_generation.get(key, 0) + 1
            self._invalidation_generation[key] = next_gen
            return next_gen

    def invalidation_generation(self, game_id: int, perspective: int) -> int:
        with self._generation_lock:
            return self._invalidation_generation.get((game_id, perspective), 0)

    def _stored_turn_numbers(self, game_id: int, perspective: int) -> list[int]:
        prefix = f"games/{game_id}/{perspective}/turns"
        try:
            segments = self._storage.list(prefix)
        except NotFoundError:
            return []
        turns: list[int] = []
        for segment in segments:
            try:
                turns.append(int(segment))
            except ValueError:
                continue
        return turns

    def _has_evidence_aggregate_in_range(
        self,
        game_id: int,
        perspective: int,
        start: int,
        end: int | None,
    ) -> bool:
        """True when an evidence aggregate exists in ``[start, end)``.

        ``end is None`` means no upper bound.
        """
        if end is not None and start >= end:
            return False
        for stored_turn in self._stored_turn_numbers(game_id, perspective):
            if stored_turn < start or (end is not None and stored_turn >= end):
                continue
            if self.get_evidence_aggregate(game_id, perspective, stored_turn) is not None:
                return True
        return False

    def _read_fleet_age_stale_document(
        self,
        game_id: int,
        perspective: int,
    ) -> FleetAgeStaleDocument | None:
        try:
            data = self._storage.get(self.fleet_age_stale_marker_key(game_id, perspective))
        except NotFoundError:
            return None
        if data is None:
            return None
        return fleet_age_stale_document_from_json(data)

    def _write_fleet_age_stale_document(
        self,
        game_id: int,
        perspective: int,
        document: FleetAgeStaleDocument,
    ) -> None:
        self._storage.put(
            self.fleet_age_stale_marker_key(game_id, perspective),
            fleet_age_stale_document_to_json(document),
        )

    def _bump_generations_for_game(self, game_id: int) -> None:
        with self._generation_lock:
            for (stored_game_id, perspective), value in list(self._invalidation_generation.items()):
                if stored_game_id == game_id:
                    self._invalidation_generation[(stored_game_id, perspective)] = value + 1
