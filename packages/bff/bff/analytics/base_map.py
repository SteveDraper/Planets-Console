"""BFF base-map analytic handler."""

from api.diagnostics import Diagnostics

from bff.analytics.models import CoreAnalyticsLoader, TurnScope, load_core_analytic

ANALYTIC_ID = "base-map"

METADATA = {
    "id": ANALYTIC_ID,
    "name": "Map",
    "supportsTable": False,
    "supportsMap": True,
    "type": "base",
}


def get_map(scope: TurnScope, load_core: CoreAnalyticsLoader, diagnostics: Diagnostics) -> dict:
    return load_core_analytic(load_core, scope, ANALYTIC_ID, diagnostics=diagnostics)
