"""Fleet observation leg: pass the prior through for approximate persist.

Ships stay off the job wire. Observation persist copies the prior, matches
this turn's visible ships, and writes the file. Finalization replaces that
file once the same-turn scoreboard result is terminal.
"""

from __future__ import annotations

from typing import Any

from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_from_json,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)
from api.compute.wire import StepResult

FLEET_PERSIST_LEG_OBSERVATION = "observation"
FLEET_PERSIST_LEG_FINALIZATION = "finalization"


def _eliminated_observation_result(job_wire: dict[str, Any]) -> StepResult:
    """Empty non-final ledger from the eliminated flag. Does not read priors."""
    player_id = int(job_wire["playerId"])
    persisted = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=player_id),
        provenance=FleetMaterializationProvenance(),
    )
    return StepResult(
        outcome="persist",
        persist_then_continue=True,
        payload={
            "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
            "materializeTurn": int(job_wire["materializeTurn"]),
            "fleetPersistLeg": FLEET_PERSIST_LEG_OBSERVATION,
            "eliminatedAtTurn": True,
        },
    )


def run_fleet_observation_leg(job_wire: dict[str, Any]) -> StepResult:
    """Pass the prior ledger through. Persist folds sightings onto that prior."""
    if job_wire.get("eliminatedAtTurn") is True:
        return _eliminated_observation_result(job_wire)

    prior_ledger_wire = job_wire.get("priorLedgerWire")
    if prior_ledger_wire is not None:
        ledger = persisted_fleet_ledger_from_json(prior_ledger_wire).ledger
    else:
        ledger = fleet_acquisition_ledger_from_json(job_wire["baselineLedgerWire"])

    provenance_wire = job_wire["provenanceWire"]
    persisted = PersistedFleetLedger(
        ledger=ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=False,
            prior_ledger_at_n_minus_1=bool(provenance_wire["priorLedgerAtNMinus1"]),
        ),
    )
    return StepResult(
        outcome="persist",
        persist_then_continue=True,
        payload={
            "persistedLedgerWire": persisted_fleet_ledger_to_json(persisted),
            "materializeTurn": int(job_wire["materializeTurn"]),
            "fleetPersistLeg": FLEET_PERSIST_LEG_OBSERVATION,
        },
    )
