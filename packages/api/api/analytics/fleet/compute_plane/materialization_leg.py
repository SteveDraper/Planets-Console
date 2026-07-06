"""Pure fleet materialization leg for compute orchestrator interpreter steps."""

from __future__ import annotations

from typing import Any

from api.analytics.fleet.compute_plane.turn_delta import (
    advance_ledger_to_turn,
    apply_fleet_turn_delta_for_player,
)
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_from_json,
    fleet_materialization_provenance_from_json,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import FleetAcquisitionLedger, PersistedFleetLedger
from api.serialization.turn import turn_info_from_json


def run_fleet_materialization_leg(job_wire: dict[str, Any]) -> dict[str, Any]:
    """Materialize one fleet turn leg from a serializable job wire (compute plane)."""
    turn = turn_info_from_json(job_wire["turnWire"])
    prior_ledger_wire = job_wire.get("priorLedgerWire")
    prior_persisted = (
        persisted_fleet_ledger_from_json(prior_ledger_wire)
        if prior_ledger_wire is not None
        else None
    )
    prior_ledger: FleetAcquisitionLedger
    if prior_persisted is not None:
        prior_ledger = prior_persisted.ledger
    else:
        prior_ledger = fleet_acquisition_ledger_from_json(job_wire["baselineLedgerWire"])

    turn_context = FleetTurnContext.from_turn(turn)
    ledger = advance_ledger_to_turn(prior_ledger, turn)
    ledger = apply_fleet_turn_delta_for_player(
        ledger,
        turn_context,
        game_id=int(job_wire["gameId"]),
        perspective=int(job_wire["perspective"]),
        inference_materialization=None,
    )
    provenance = fleet_materialization_provenance_from_json(job_wire["provenanceWire"])
    persisted = PersistedFleetLedger(ledger=ledger, provenance=provenance)
    return {
        "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
        "materializeTurn": int(job_wire["materializeTurn"]),
    }
