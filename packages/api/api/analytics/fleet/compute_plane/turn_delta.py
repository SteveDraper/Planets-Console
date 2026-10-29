"""Copy a player's fleet ledger forward one turn."""

from __future__ import annotations

import copy

from api.analytics.fleet.types import FleetAcquisitionLedger
from api.analytics.turn_roster import iter_turn_players
from api.models.game import TurnInfo


def advance_ledger_to_turn(
    prior_ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
) -> FleetAcquisitionLedger:
    """Copy one player's ledger forward to shell turn T."""
    ledger = copy.deepcopy(prior_ledger)
    for player in iter_turn_players(turn):
        if player.id == ledger.player_id:
            ledger.player_name = player.username
            break
    return ledger


def copy_prior_for_approximate(
    prior_ledger: FleetAcquisitionLedger,
    turn: TurnInfo,
) -> FleetAcquisitionLedger:
    """Copy every prior ship, disposition, and evidence event. Drop its discrepancy."""
    ledger = advance_ledger_to_turn(prior_ledger, turn)
    ledger.discrepancy = None
    return ledger
