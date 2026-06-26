"""Per-analytic export service bundles for fleet."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.constants import ANALYTIC_ID


def resolve_fleet_export_services(ctx: AnalyticQueryContext) -> FleetComputeServices:
    services = export_service_for(ctx, ANALYTIC_ID, FleetComputeServices)
    if services is not None:
        return services

    injected = ctx.export_services.get(ANALYTIC_ID)
    if injected is None:
        raise RuntimeError(
            f"Fleet export requires {ANALYTIC_ID!r} in ctx.export_services; "
            "inject FleetComputeServices via TurnAnalyticService or test helpers."
        )
    raise RuntimeError(
        f"Fleet export_services[{ANALYTIC_ID!r}] must be FleetComputeServices, "
        f"got {type(injected).__name__}."
    )
