"""Fleet compute service bundle and the none-returning context lookup.

Ledger readers import this module. It does not import held solutions, so
resolving services does not load the scores package.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.fleet.held_solutions import FleetInferenceMaterialization


@dataclass(frozen=True)
class FleetComputeServices:
    persistence: FleetSnapshotPersistenceService
    game_id: int
    perspective: int
    load_turn: Callable[[int], TurnInfo | None]
    inference_materialization: FleetInferenceMaterialization | None = None


def lookup_fleet_compute_services(ctx: AnalyticQueryContext) -> FleetComputeServices | None:
    """Return fleet compute services when this query context has them."""
    return export_service_for(ctx, ANALYTIC_ID, FleetComputeServices)


def resolve_fleet_services(exports: AnalyticQueryContext) -> FleetComputeServices:
    """Return fleet compute services, or raise when the context has none."""
    services = lookup_fleet_compute_services(exports)
    if services is not None:
        return services

    injected = exports.export_services.get(ANALYTIC_ID)
    if injected is None:
        raise RuntimeError(
            f"Fleet requires {ANALYTIC_ID!r} in ctx.export_services; "
            "inject FleetComputeServices via TurnAnalyticService or test helpers."
        )
    raise RuntimeError(
        f"Fleet export_services[{ANALYTIC_ID!r}] must be FleetComputeServices, "
        f"got {type(injected).__name__}."
    )
