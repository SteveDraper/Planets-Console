"""Core Connections analytic adapter."""

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.concepts.planet_connections import connection_routes_with_options
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.transport.connections_options import FlareConnectionMode

ANALYTIC_ID = "connections"


def compute_connections_map(ctx: AnalyticComputeContext) -> dict:
    """Return connection route pairs for the selected turn."""
    turn = ctx.turn
    options = ctx.options
    warp = options.connection_warp_speed if options.connection_warp_speed is not None else 9
    if warp < 1 or warp > 9:
        raise ValidationError("warpSpeed must be between 1 and 9.")
    if options.connection_flare_depth < 1 or options.connection_flare_depth > 3:
        raise ValidationError("flareDepth must be 1, 2, or 3.")
    try:
        flare_mode = FlareConnectionMode(options.connection_flare_mode)
    except ValueError as err:
        raise ValidationError("flareMode must be off, include, or only.") from err
    out = connection_routes_with_options(
        list(turn.planets),
        warp_speed=warp,
        gravitonic_movement=options.connection_gravitonic_movement,
        flare_mode=flare_mode,
        flare_depth=options.connection_flare_depth,
        diagnostics=ctx.diagnostics,
        include_illustrative_routes=options.connection_include_illustrative_routes,
    )
    return {
        "analyticId": ANALYTIC_ID,
        "nodes": [],
        "edges": [],
        "routes": out.routes,
    }


def get_connections_map(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(compute_connections_map, turn, options)


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_connections_map,
)
