"""Coordinate fleet snapshot invalidation on turn document writes."""

from __future__ import annotations

from api.analytics.fleet.persistence import FleetSnapshotPersistenceService


class FleetInvalidationService:
    def __init__(self, persistence: FleetSnapshotPersistenceService) -> None:
        self._persistence = persistence

    def on_turn_stored(self, game_id: int, perspective: int, turn_number: int) -> set[int]:
        """Drop fleet snapshots at turns >= turn_number after a turn document replace.

        Scores inference invalidation (pair-aware T/T-1) is handled separately.
        Fleet/scores cross-invalidation when scores rows change without a turn
        rewrite is deferred to fleet export ensure work (#119--#121).
        """
        return self._persistence.invalidate_for_turn_write(game_id, perspective, turn_number)
