"""Fleet observation leg: approximate fleet without a same-turn scoreboard solve.

The interpreter copies the prior ledger. Ships stay off that job wire, so the
observation persist matches this turn's visible ships and writes the file.
Finalization replaces that file once the same-turn scoreboard result is terminal.
"""

from __future__ import annotations

from typing import Any

from api.analytics.fleet.compute_plane.turn_delta import copy_prior_for_approximate
from api.analytics.fleet.scoreboard_slice import turn_from_fleet_scoreboard_slice
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
    """Copy the prior ledger for one fleet turn. Persist matches sightings."""
    if job_wire.get("eliminatedAtTurn") is True:
        return _eliminated_observation_result(job_wire)

    turn = turn_from_fleet_scoreboard_slice(job_wire["turnWire"])
    prior_ledger_wire = job_wire.get("priorLedgerWire")
    if prior_ledger_wire is not None:
        prior_ledger = persisted_fleet_ledger_from_json(prior_ledger_wire).ledger
    else:
        prior_ledger = fleet_acquisition_ledger_from_json(job_wire["baselineLedgerWire"])

    ledger = copy_prior_for_approximate(prior_ledger, turn)
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
