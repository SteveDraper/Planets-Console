"""Injected services for fleet analytic compute and snapshot chaining."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo

ANALYTIC_ID = "fleet"


@dataclass(frozen=True)
class FleetComputeServices:
    persistence: FleetSnapshotPersistenceService
    game_id: int
    perspective: int
    load_turn: Callable[[int], TurnInfo | None]


def resolve_fleet_compute_services(ctx: AnalyticComputeContext) -> FleetComputeServices | None:
    injected = ctx.exports.export_services.get(ANALYTIC_ID)
    if injected is None:
        return None
    if not isinstance(injected, FleetComputeServices):
        raise RuntimeError(
            f"Fleet compute export_services[{ANALYTIC_ID!r}] must be FleetComputeServices, "
            f"got {type(injected).__name__}."
        )
    return injected
