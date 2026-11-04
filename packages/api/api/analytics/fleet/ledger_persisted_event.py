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


@dataclass(frozen=True)
class FleetAgeIdentityChanged:
    """One player's on-disk ``ship_id -> built_turn`` map was created, removed, or edited.

    This is not the ensure-final ledger side channel. Approximate writes and
    generation-behind files notify here when the build-turn identity changes.
    """

    game_id: int
    perspective: int
    turn: int
    player_id: int
