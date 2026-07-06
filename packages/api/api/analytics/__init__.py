"""Core turn analytics."""

from __future__ import annotations

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AnalyticComputeContext": ("api.analytics.compute_context", "AnalyticComputeContext"),
    "AnalyticQueryContext": ("api.analytics.export_context", "AnalyticQueryContext"),
    "AnalyticExportCatalog": ("api.analytics.exports.catalog", "AnalyticExportCatalog"),
    "catalog_entry": ("api.analytics.catalog", "catalog_entry"),
    "TURN_ANALYTIC_CATALOG": ("api.analytics.catalog", "TURN_ANALYTIC_CATALOG"),
    "TurnAnalyticCatalogEntry": ("api.analytics.catalog", "TurnAnalyticCatalogEntry"),
    "TurnAnalyticHandler": ("api.analytics.registration", "TurnAnalyticHandler"),
    "TurnAnalyticRegistration": ("api.analytics.registration", "TurnAnalyticRegistration"),
    "TurnAnalyticsOptions": ("api.analytics.options", "TurnAnalyticsOptions"),
}

_LAZY_REGISTRY_EXPORTS = frozenset(
    {
        "TURN_ANALYTIC_REGISTRATIONS",
        "TURN_ANALYTICS",
        "get_turn_analytic",
    }
)

__all__ = [
    *sorted(_LAZY_EXPORTS),
    *sorted(_LAZY_REGISTRY_EXPORTS),
]


def __getattr__(name: str) -> object:
    if name in _LAZY_REGISTRY_EXPORTS:
        from api.analytics import registry as registry_module

        return getattr(registry_module, name)
    spec = _LAZY_EXPORTS.get(name)
    if spec is not None:
        module_path, attr = spec
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
