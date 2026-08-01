"""Read, write, and invalidate homeworld locator persistence documents."""

from __future__ import annotations

import threading

from api.analytics.homeworld_locator.constants import (
    ANALYTIC_ID,
    ATTRIBUTION_USER_ASSERTED,
)
from api.analytics.homeworld_locator.serialization import (
    homeworld_evidence_aggregate_from_json,
    homeworld_evidence_aggregate_to_json,
    homeworld_locator_game_state_from_json,
    homeworld_locator_game_state_to_json,
)
from api.analytics.homeworld_locator.types import (
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
)
from api.analytics.persistence_paths import (
    game_global_analytic_document_key,
    turn_scoped_analytic_document_key,
)
from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend


class HomeworldLocatorPersistenceService:
    """Persist game-global candidates and turn-scoped evidence aggregates.

    Logical paths (ADR 0002):
    - Game-global: ``games/{gameId}/analytics/homeworld-locator``
    - Evidence: ``games/{gameId}/{perspective}/turns/{turn}/analytics/homeworld-locator``
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage
        self._invalidation_generation: dict[tuple[int, int], int] = {}
        self._generation_lock = threading.Lock()

    @staticmethod
    def game_global_document_key(game_id: int) -> str:
        return game_global_analytic_document_key(game_id, ANALYTIC_ID)

    @staticmethod
    def evidence_document_key(game_id: int, perspective: int, turn_number: int) -> str:
        return turn_scoped_analytic_document_key(game_id, perspective, turn_number, ANALYTIC_ID)

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

    def invalidate_inferred_game_state(self, game_id: int) -> HomeworldLocatorGameState | None:
        """Drop inferred game-global candidates; preserve user-asserted rows when present."""
        existing = self.get_game_state(game_id)
        if existing is None:
            return None
        preserved = tuple(
            row for row in existing.candidates if row.attribution == ATTRIBUTION_USER_ASSERTED
        )
        if not preserved:
            try:
                self._storage.delete(self.game_global_document_key(game_id))
            except NotFoundError:
                pass
            self._bump_generations_for_game(game_id)
            return None
        retained = HomeworldLocatorGameState(
            candidates=preserved,
            baseline_turn=existing.baseline_turn,
            baseline_degraded=existing.baseline_degraded,
            settings_fingerprint=(),
            baseline_algorithm_version=existing.baseline_algorithm_version,
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
        prefix = f"games/{game_id}/{perspective}/turns"
        try:
            turn_segments = self._storage.list(prefix)
        except NotFoundError:
            return []
        cleared: list[int] = []
        for segment in turn_segments:
            try:
                stored_turn = int(segment)
            except ValueError:
                continue
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

    def _bump_generations_for_game(self, game_id: int) -> None:
        with self._generation_lock:
            for (stored_game_id, perspective), value in list(self._invalidation_generation.items()):
                if stored_game_id == game_id:
                    self._invalidation_generation[(stored_game_id, perspective)] = value + 1
