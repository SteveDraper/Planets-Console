"""BFF analytics metadata and dispatch."""

from api.diagnostics import Diagnostics

from bff.analytics import base_map, connections, placeholder, scores
from bff.analytics.models import ConnectionsMapQuery, CoreAnalyticsLoader, TurnScope

ANALYTICS_LIST = [
    base_map.METADATA,
    scores.METADATA,
    placeholder.TABLE_METADATA,
    connections.METADATA,
    placeholder.MAP_METADATA,
    placeholder.BOTH_METADATA,
]

TABLE_HANDLERS = {
    scores.ANALYTIC_ID: scores.get_table,
}

MAP_HANDLERS = {
    base_map.ANALYTIC_ID: base_map.get_map,
    connections.ANALYTIC_ID: connections.get_map,
}


def get_table_response(
    analytic_id: str,
    scope: TurnScope,
    load_core: CoreAnalyticsLoader,
) -> dict:
    handler = TABLE_HANDLERS.get(analytic_id)
    if handler is None:
        return placeholder.get_table(analytic_id)
    return handler(scope, load_core)


def map_diagnostic_values(analytic_id: str, query: ConnectionsMapQuery) -> dict:
    if analytic_id == connections.ANALYTIC_ID:
        return connections.diagnostic_values(query)
    return {}


def map_timing_section(analytic_id: str) -> str:
    if analytic_id in MAP_HANDLERS:
        return "turn_analytics_from_core"
    return "total"


def get_map_response(
    analytic_id: str,
    scope: TurnScope,
    query: ConnectionsMapQuery,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    if analytic_id == base_map.ANALYTIC_ID:
        return base_map.get_map(scope, load_core, diagnostics)
    if analytic_id == connections.ANALYTIC_ID:
        return connections.get_map(scope, query, load_core, diagnostics)
    return placeholder.get_map(analytic_id)
