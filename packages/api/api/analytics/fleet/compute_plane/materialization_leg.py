"""Pure fleet materialization leg for compute orchestrator interpreter steps.

Phase 1 of two-phase fleet materialization: advance the acquisition ledger one
turn in the interpreter compute plane without scores inference or observation
ingest. Phase 2 is ``FleetPersistencePolicy.persist`` in ``compute_orchestration``,
which applies inference, then id bounds and ship observations, and may refresh
provenance before storage.
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


def run_fleet_materialization_leg(job_wire: dict[str, Any]) -> StepResult:
    """Materialize one fleet turn leg from a serializable job wire (compute plane).

    Returns a persisted-ledger wire carrying provenance from the job wire.
    Scores inference is deferred to the orchestration persist hook.
    """
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
        inference_materialization=None,  # phase 2 persist hook owns scores inference
        apply_observations=False,  # observations run after refine in persist
    )
    provenance = fleet_materialization_provenance_from_json(job_wire["provenanceWire"])
    persisted = PersistedFleetLedger(ledger=ledger, provenance=provenance)
    return StepResult(
        outcome="persist",
        payload={
            "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
            "materializeTurn": int(job_wire["materializeTurn"]),
        },
    )
