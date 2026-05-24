"""BFF Connections map analytic handler."""

from api.diagnostics import Diagnostics
from api.transport.connections_options import (
    FLARE_DEPTH_QUERY,
    FLARE_MODE_QUERY,
    GRAVITONIC_MOVEMENT_QUERY,
    INCLUDE_ILLUSTRATIVE_ROUTES_QUERY,
    WARP_SPEED_QUERY,
)

from bff.analytics.models import (
    ConnectionsMapQuery,
    CoreAnalyticsLoader,
    TurnScope,
    load_core_analytic,
)

ANALYTIC_ID = "connections"

METADATA = {
    "id": ANALYTIC_ID,
    "name": "Connections",
    "supportsTable": False,
    "supportsMap": True,
    "type": "selectable",
}


def diagnostic_values(query: ConnectionsMapQuery) -> dict:
    return {
        WARP_SPEED_QUERY: query.warp_speed,
        GRAVITONIC_MOVEMENT_QUERY: query.gravitonic_movement,
        FLARE_MODE_QUERY: str(query.flare_mode.value),
        FLARE_DEPTH_QUERY: query.flare_depth,
        INCLUDE_ILLUSTRATIVE_ROUTES_QUERY: query.include_illustrative_routes,
    }


def get_map(
    scope: TurnScope,
    query: ConnectionsMapQuery,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    return load_core_analytic(
        load_core,
        scope,
        ANALYTIC_ID,
        diagnostics=diagnostics,
        connection_warp_speed=query.warp_speed,
        connection_gravitonic_movement=query.gravitonic_movement,
        connection_flare_mode=query.flare_mode.value,
        connection_flare_depth=query.flare_depth,
        connection_include_illustrative_routes=query.include_illustrative_routes,
    )
