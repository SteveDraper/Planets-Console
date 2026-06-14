"""Core turn analytics."""

from api.analytics.catalog import TurnAnalyticCatalogEntry, catalog_entry
from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import (
    EmptyExportCatalog,
    TurnAnalyticHandler,
    TurnAnalyticRegistration,
)

__all__ = [
    "AnalyticComputeContext",
    "EmptyExportCatalog",
    "catalog_entry",
    "TURN_ANALYTIC_CATALOG",
    "TURN_ANALYTIC_REGISTRATIONS",
    "TURN_ANALYTICS",
    "TurnAnalyticCatalogEntry",
    "TurnAnalyticHandler",
    "TurnAnalyticRegistration",
    "TurnAnalyticsOptions",
    "get_turn_analytic",
]

_LAZY_REGISTRY_EXPORTS = frozenset(
    {
        "TURN_ANALYTIC_CATALOG",
        "TURN_ANALYTIC_REGISTRATIONS",
        "TURN_ANALYTICS",
        "get_turn_analytic",
    }
)


def __getattr__(name: str):
    if name in _LAZY_REGISTRY_EXPORTS:
        from api.analytics import registry as registry_module

        return getattr(registry_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
