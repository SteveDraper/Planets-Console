"""Fleet observation leg: ask persist to write the approximate fleet.

Ships and the prior ledger stay off the job wire. Observation persist loads
the prior from fleet storage, matches this turn's visible ships once, and
writes the file. Finalization replaces that file once the same-turn scoreboard
result is terminal. An eliminated player is a flag only.
"""

from __future__ import annotations

from typing import Any

from api.compute.wire import StepResult

FLEET_PERSIST_LEG_OBSERVATION = "observation"
FLEET_PERSIST_LEG_FINALIZATION = "finalization"


def run_fleet_observation_leg(job_wire: dict[str, Any]) -> StepResult:
    """Hand off to observation persist. The payload does not carry a ledger."""
    payload: dict[str, Any] = {
        "materializeTurn": int(job_wire["materializeTurn"]),
        "fleetPersistLeg": FLEET_PERSIST_LEG_OBSERVATION,
    }
    if job_wire.get("eliminatedAtTurn") is True:
        payload["eliminatedAtTurn"] = True
    return StepResult(
        outcome="persist",
        persist_then_continue=True,
        payload=payload,
    )
