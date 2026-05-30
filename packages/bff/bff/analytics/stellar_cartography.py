"""BFF Stellar Cartography map analytic handler."""

from api.diagnostics import Diagnostics

from bff.analytics.descriptor import AnalyticDescriptor
from bff.analytics.models import (
    ConnectionsMapQuery,
    CoreAnalyticsLoader,
    TurnScope,
    load_core_analytic,
)

ANALYTIC_ID = "stellar-cartography"


def get_map(
    scope: TurnScope,
    _query: ConnectionsMapQuery,
    load_core: CoreAnalyticsLoader,
    diagnostics: Diagnostics,
) -> dict:
    return load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)


DESCRIPTOR = AnalyticDescriptor(
    id=ANALYTIC_ID,
    name="Stellar Cartography",
    supports_table=False,
    supports_map=True,
    type="selectable",
    get_map=get_map,
)
