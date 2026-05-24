"""BFF analytics catalog and dispatch."""

from api.diagnostics import Diagnostics

from bff.analytics.descriptor import AnalyticDescriptor
from bff.analytics.models import ConnectionsMapQuery, CoreAnalyticsLoader, TurnScope
from bff.errors import BFFValidationError

from . import base_map, connections, scores

REGISTERED_ANALYTICS: tuple[AnalyticDescriptor, ...] = (
    base_map.DESCRIPTOR,
    scores.DESCRIPTOR,
    connections.DESCRIPTOR,
)

_BY_ID: dict[str, AnalyticDescriptor] = {
    descriptor.id: descriptor for descriptor in REGISTERED_ANALYTICS
}

ANALYTICS_LIST = [descriptor.metadata() for descriptor in REGISTERED_ANALYTICS]


def _require_descriptor(analytic_id: str) -> AnalyticDescriptor:
    try:
        return _BY_ID[analytic_id]
    except KeyError as err:
        raise BFFValidationError(f"Unknown analytic_id: {analytic_id!r}") from err


def get_table_response(
    analytic_id: str,
    scope: TurnScope,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    descriptor = _require_descriptor(analytic_id)
    if descriptor.get_table is None:
        raise BFFValidationError(f"Analytic {analytic_id!r} does not support table view")
    return descriptor.get_table(scope, load_core, diagnostics)


def map_diagnostic_values(analytic_id: str, query: ConnectionsMapQuery) -> dict:
    descriptor = _BY_ID.get(analytic_id)
    if descriptor is None or descriptor.map_diagnostic_values is None:
        return {}
    return descriptor.map_diagnostic_values(query)


def map_timing_section(analytic_id: str) -> str:
    descriptor = _BY_ID.get(analytic_id)
    if descriptor is None or descriptor.get_map is None:
        return "total"
    return descriptor.map_timing_section


def get_map_response(
    analytic_id: str,
    scope: TurnScope,
    query: ConnectionsMapQuery,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    descriptor = _require_descriptor(analytic_id)
    if descriptor.get_map is None:
        raise BFFValidationError(f"Analytic {analytic_id!r} does not support map view")
    return descriptor.get_map(scope, query, load_core, diagnostics)
