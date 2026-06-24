"""Read, write, and invalidate fleet turn snapshots."""

from __future__ import annotations

from api.analytics.fleet.serialization import (
    fleet_turn_snapshot_from_json,
    fleet_turn_snapshot_to_json,
)
from api.analytics.fleet.types import FleetTurnSnapshot
from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend

ANALYTIC_ID = "fleet"


class FleetSnapshotPersistenceService:
    """Persist fleet acquisition ledgers at turn-scoped analytic breakpoints.

    Logical document path:
    ``games/{gameId}/{perspective}/turns/{turn}/analytics/fleet``

    Scores-invalidation coupling (F2.x): when scores inference rows are cleared
    for host turn *H*, fleet snapshots at turns ``>= H`` for the same perspective
    must be re-materialized so build evidence and reconciliation stay aligned.
    Fleet turn-document invalidation (``invalidate_for_turn_write``) is independent
    of scores pair-aware invalidation (turn *T* and *T-1*); both hooks run from
    ``on_turn_stored`` today. Scores-only invalidation (hull mask, recompute) does
    not yet cascade into fleet -- that coupling lands with fleet/scores export ensure
    (#119--#121).
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

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

    def put_snapshot(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
        snapshot: FleetTurnSnapshot,
    ) -> None:
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
            if self.get_snapshot(game_id, perspective, stored_turn) is None:
                continue
            self.delete_snapshot(game_id, perspective, stored_turn)
            cleared.add(stored_turn)
        return cleared

    def _stored_turn_numbers(self, game_id: int, perspective: int) -> list[int]:
        turns_prefix = f"games/{game_id}/{perspective}/turns"
        try:
            segments = self._storage.list(turns_prefix)
        except (NotFoundError, ValidationError):
            return []
        turn_numbers: list[int] = []
        for segment in segments:
            if segment.isdigit():
                turn_numbers.append(int(segment))
        return sorted(turn_numbers)
