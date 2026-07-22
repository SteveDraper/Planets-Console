"""Fleet observation leg: host materialization without scores inference.

Writes a non-final ledger (placeholders / turn delta only) and continues to
finalization. Scores refine and ship-observation ingest run in the finalization
persist hook so option sets exist before observation matching.
"""

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
from api.compute.wire import StepResult
from api.compute.worker_turn_cache import turn_from_materialization_job_wire

FLEET_PERSIST_LEG_OBSERVATION = "observation"
FLEET_PERSIST_LEG_FINALIZATION = "finalization"


def run_fleet_observation_leg(job_wire: dict[str, Any]) -> StepResult:
    """Materialize one fleet turn observation leg from a serializable job wire."""
    turn = turn_from_materialization_job_wire(job_wire)
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
    return StepResult(
        outcome="persist",
        persist_then_continue=True,
        payload={
            "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
            "materializeTurn": int(job_wire["materializeTurn"]),
            "fleetPersistLeg": FLEET_PERSIST_LEG_OBSERVATION,
        },
    )
