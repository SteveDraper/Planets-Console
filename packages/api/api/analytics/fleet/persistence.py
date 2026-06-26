"""Read, write, and invalidate fleet turn snapshots."""

from __future__ import annotations

import threading

from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.serialization import (
    fleet_turn_snapshot_from_json,
    fleet_turn_snapshot_to_json,
)
from api.analytics.fleet.types import FleetTurnSnapshot
from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend


class FleetSnapshotPersistenceService:
    """Persist fleet acquisition ledgers at turn-scoped analytic breakpoints.

    Logical document path:
    ``games/{gameId}/{perspective}/turns/{turn}/analytics/fleet``

    Scores-invalidation coupling (F2.x): when scores inference rows are cleared
    for host turn *H*, fleet snapshots at turns ``>= H`` for the same perspective
    must be re-materialized so build evidence and reconciliation stay aligned.
    ``InferenceInvalidationService.on_inference_evidence_updated`` performs that
    invalidation when inference rows are persisted or held solutions stream in.
    Fleet turn-document invalidation (``invalidate_for_turn_write``) is independent
    of scores pair-aware invalidation (turn *T* and *T-1*); both hooks run from
    ``on_turn_stored`` today.

    **Invalidation generation:** Each ``(game_id, perspective)`` pair has a
    monotonic counter bumped on every ``invalidate_for_turn_write`` call. Gap-fill
    in ``get_or_materialize_fleet_snapshot`` records the generation at chain start
    and aborts (then retries from a fresh anchor) when the counter advances during
    multi-turn materialization. Invalidation does not block on gap-fill; concurrent
    invalidation callbacks only bump the counter and delete stored snapshots.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage
        self._invalidation_generation: dict[tuple[int, int], int] = {}
        self._generation_lock = threading.Lock()

    @staticmethod
    def document_key(game_id: int, perspective: int, turn_number: int) -> str:
        return f"games/{game_id}/{perspective}/turns/{turn_number}/analytics/{ANALYTIC_ID}"

    def get_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> FleetTurnSnapshot | None:
        try:
            data = self._storage.get(self.document_key(game_id, perspective, turn_number))
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("stored fleet turn snapshot must be a JSON object")
        return fleet_turn_snapshot_from_json(data)

    def has_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> bool:
        try:
            data = self._storage.get(self.document_key(game_id, perspective, turn_number))
        except NotFoundError:
            return False
        return data is not None

    def put_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        snapshot: FleetTurnSnapshot,
    ) -> None:
        if snapshot.game_id != game_id:
            raise ValidationError(
                f"fleet snapshot game_id {snapshot.game_id} does not match key game_id {game_id}"
            )
        if snapshot.perspective != perspective:
            raise ValidationError(
                "fleet snapshot perspective "
                f"{snapshot.perspective} does not match key perspective {perspective}"
            )
        if snapshot.turn != turn_number:
            raise ValidationError(
                f"fleet snapshot turn {snapshot.turn} does not match key turn_number {turn_number}"
            )
        self._storage.put(
            self.document_key(game_id, perspective, turn_number),
            fleet_turn_snapshot_to_json(snapshot),
        )

    def delete_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> None:
        try:
            self._storage.delete(self.document_key(game_id, perspective, turn_number))
        except NotFoundError:
            pass

    def invalidation_generation(self, game_id: int, perspective: int) -> int:
        """Return the current invalidation generation for one perspective scope."""
        with self._generation_lock:
            return self._invalidation_generation.get((game_id, perspective), 0)

    def invalidate_for_turn_write(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> set[int]:
        """Drop fleet snapshots at turns >= turn_number for one perspective."""
        cleared: set[int] = set()
        for stored_turn in self._stored_turn_numbers(game_id, perspective):
            if stored_turn < turn_number:
                continue
            if not self.has_snapshot(game_id, perspective, stored_turn):
                continue
            self.delete_snapshot(game_id, perspective, stored_turn)
            cleared.add(stored_turn)
        self._bump_invalidation_generation(game_id, perspective)
        return cleared

    def _bump_invalidation_generation(self, game_id: int, perspective: int) -> None:
        with self._generation_lock:
            key = (game_id, perspective)
            self._invalidation_generation[key] = self._invalidation_generation.get(key, 0) + 1

    def _stored_turn_numbers(self, game_id: int, perspective: int) -> list[int]:
        turns_prefix = f"games/{game_id}/{perspective}/turns"
        try:
            segments = self._storage.list(turns_prefix)
        except NotFoundError, ValidationError:
            return []
        turn_numbers: list[int] = []
        for segment in segments:
            if segment.isdigit():
                turn_numbers.append(int(segment))
        return sorted(turn_numbers)
