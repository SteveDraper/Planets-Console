"""Pure fleet materialization leg for compute orchestrator interpreter steps.

Copies the prior ledger without scoreboard acquisitions. Sighting match and the
file write live on observation persist. Finalization replaces the file once
same-turn scores are terminal.
"""

from __future__ import annotations

from typing import Any

from api.analytics.fleet.compute_plane.turn_delta import copy_prior_for_approximate
from api.analytics.fleet.scoreboard_slice import turn_from_fleet_scoreboard_slice
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_from_json,
    fleet_materialization_provenance_from_json,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import FleetAcquisitionLedger, PersistedFleetLedger
from api.compute.wire import StepResult


def run_fleet_materialization_leg(job_wire: dict[str, Any]) -> StepResult:
    """Materialize one fleet turn leg from a serializable job wire (compute plane).

    Returns a persisted-ledger wire carrying provenance from the job wire.
    Scores inference is deferred to the orchestration persist hook.
    """
    turn = turn_from_fleet_scoreboard_slice(job_wire["turnWire"])
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

    ledger = copy_prior_for_approximate(prior_ledger, turn)
    provenance = fleet_materialization_provenance_from_json(job_wire["provenanceWire"])
    persisted = PersistedFleetLedger(ledger=ledger, provenance=provenance)
    return StepResult(
        outcome="persist",
        payload={
            "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
            "materializeTurn": int(job_wire["materializeTurn"]),
        },
    )
