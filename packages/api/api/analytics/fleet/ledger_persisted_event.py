"""Fleet per-player ledger persistence notifications."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FleetLedgerPersistedEvent:
    """Notification that one player's fleet ledger reached ensure-final persistence."""

    game_id: int
    perspective: int
    fleet_turn: int
    player_id: int
    materialization_version: int
    source_context_id: int | None = None
