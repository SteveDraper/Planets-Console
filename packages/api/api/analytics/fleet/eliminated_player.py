"""Empty final fleet ledger when the scoped player is eliminated on this turn."""

from __future__ import annotations

from api.analytics.fleet.types import FleetAcquisitionLedger, FleetMaterializationProvenance
from api.analytics.turn_roster import players_by_id
from api.models.game import TurnInfo
from api.services.player_elimination import is_eliminated_at_turn


def fleet_player_eliminated_at_turn(turn: TurnInfo, player_id: int) -> bool:
    """True when this player's row is eliminated on ``turn.settings.turn``.

    Uses ``is_eliminated_at_turn`` (``status == ELIMINATED`` and
    ``turn >= statusturn``). A missing row, ``username == "dead"``, or
    ``statusturn`` without elimination is not death.
    """
    player = players_by_id(turn).get(player_id)
    if player is None:
        return False
    return is_eliminated_at_turn(player, turn.settings.turn)


def eliminated_empty_fleet_ledger(turn: TurnInfo, player_id: int) -> FleetAcquisitionLedger:
    """Ship-free ledger for an eliminated player. Does not read a prior turn."""
    player = players_by_id(turn).get(player_id)
    return FleetAcquisitionLedger(
        player_id=player_id,
        player_name=player.username if player is not None else "",
    )


def eliminated_fleet_provenance() -> FleetMaterializationProvenance:
    """Final because the player is eliminated, not because chain inputs arrived."""
    return FleetMaterializationProvenance(eliminated_at_turn=True)
