"""Fleet finalization leg: scores refine and durable final ledger persist."""

from __future__ import annotations

from typing import Any

from api.analytics.fleet.compute_plane.observation_leg import FLEET_PERSIST_LEG_FINALIZATION
from api.compute.wire import StepResult


def run_fleet_finalization_leg(job_wire: dict[str, Any]) -> StepResult:
    """Hand off observation wire to the finalization persist hook."""
    payload = dict(job_wire)
    payload["fleetPersistLeg"] = FLEET_PERSIST_LEG_FINALIZATION
    return StepResult(outcome="persist", payload=payload)
