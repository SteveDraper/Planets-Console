"""BFF Homeworld locator analytic handlers (passthrough; Phase 2 Core wire-up)."""

from api.analytics.catalog import catalog_entry
from api.diagnostics import Diagnostics

from bff.analytics.descriptor import AnalyticDescriptor
from bff.analytics.models import (
    ConnectionsMapQuery,
    CoreAnalyticsLoader,
    TurnScope,
    load_core_analytic,
)

ANALYTIC_ID = "homeworld-locator"


def get_table(
    scope: TurnScope,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    return load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)


def get_map(
    scope: TurnScope,
    _query: ConnectionsMapQuery,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    return load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)


DESCRIPTOR = AnalyticDescriptor.from_catalog_entry(
    catalog_entry(ANALYTIC_ID),
    get_table=get_table,
    get_map=get_map,
)
