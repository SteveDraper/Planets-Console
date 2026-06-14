"""BFF analytics catalog and dispatch."""

import api.analytics.registry  # noqa: F401 -- publishes TURN_ANALYTIC_CATALOG into catalog
from api.analytics.catalog import TURN_ANALYTIC_CATALOG, tuple_aligned_with_turn_analytic_catalog
from api.diagnostics import Diagnostics

from bff.analytics.descriptor import AnalyticDescriptor
from bff.analytics.models import ConnectionsMapQuery, CoreAnalyticsLoader, TurnScope
from bff.errors import BFFValidationError

from . import base_map, connections, scores, stellar_cartography

_BFF_DESCRIPTORS_BY_ID: dict[str, AnalyticDescriptor] = {
    base_map.DESCRIPTOR.id: base_map.DESCRIPTOR,
    scores.DESCRIPTOR.id: scores.DESCRIPTOR,
    connections.DESCRIPTOR.id: connections.DESCRIPTOR,
    stellar_cartography.DESCRIPTOR.id: stellar_cartography.DESCRIPTOR,
}


REGISTERED_ANALYTICS: tuple[AnalyticDescriptor, ...] = tuple_aligned_with_turn_analytic_catalog(
    _BFF_DESCRIPTORS_BY_ID,
    TURN_ANALYTIC_CATALOG,
    role="BFF descriptors",
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
    *,
    include_build_inference: bool = False,
) -> dict:
    descriptor = _require_descriptor(analytic_id)
    if descriptor.get_table is None:
        raise BFFValidationError(f"Analytic {analytic_id!r} does not support table view")
    if analytic_id == "scores":
        return descriptor.get_table(
            scope,
            load_core,
            diagnostics,
            include_build_inference=include_build_inference,
        )
    return descriptor.get_table(scope, load_core, diagnostics)


def get_inference_response(
    analytic_id: str,
    scope: TurnScope,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
    *,
    player_id: int,
) -> dict:
    if analytic_id != "scores":
        raise BFFValidationError(f"Analytic {analytic_id!r} does not support inference")
    core_inference = load_core(
        scope.game_id,
        scope.perspective,
        scope.turn,
        analytic_id,
        diagnostics=diagnostics,
        player_id=player_id,
        inference_only=True,
    )
    return scores.inference_from_core(core_inference, player_id=player_id)


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
