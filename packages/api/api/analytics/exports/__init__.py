"""Analytic export catalogs and registry."""

from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.empty import empty_export_catalog_for

__all__ = [
    "AnalyticExportCatalog",
    "EXPORT_REGISTRY",
    "empty_export_catalog_for",
]


def __getattr__(name: str):
    if name == "EXPORT_REGISTRY":
        from api.analytics.exports.registry import EXPORT_REGISTRY

        return EXPORT_REGISTRY
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
