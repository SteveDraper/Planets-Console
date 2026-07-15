"""One-turn fleet delta materialization for the compute plane."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from api.analytics.fleet.inferred_acquisition_ingest import ingest_player_inferred_acquisitions
from api.analytics.fleet.observation_ingest import ingest_player_ship_observations
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import FleetAcquisitionLedger
from api.analytics.turn_roster import iter_turn_players
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.fleet.held_solutions import FleetInferenceMaterialization


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


def apply_fleet_turn_delta_for_player(
    ledger: FleetAcquisitionLedger,
    turn_context: FleetTurnContext,
    *,
    game_id: int,
    perspective: int,
    inference_materialization: FleetInferenceMaterialization | None = None,
) -> FleetAcquisitionLedger:
    """Apply turn-T fleet evidence deltas for one player ledger."""
    turn = turn_context.turn
    ingest_player_inferred_acquisitions(
        ledger,
        turn,
        game_id=game_id,
        perspective=perspective,
        inference_materialization=inference_materialization,
    )
    ingest_player_ship_observations(ledger, turn_context, perspective=perspective)
    return ledger
