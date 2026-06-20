"""Aggregate export catalogs and validate against turn analytic catalog."""

from __future__ import annotations

from api.analytics.base_map_exports import EXPORT_CATALOG as BASE_MAP_EXPORT_CATALOG
from api.analytics.catalog import TURN_ANALYTIC_CATALOG
from api.analytics.connections_exports import EXPORT_CATALOG as CONNECTIONS_EXPORT_CATALOG
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.scores_exports import EXPORT_CATALOG as SCORES_EXPORT_CATALOG
from api.analytics.stellar_cartography_exports import (
    EXPORT_CATALOG as STELLAR_CARTOGRAPHY_EXPORT_CATALOG,
)

_PRODUCTION_EXPORT_CATALOGS: tuple[AnalyticExportCatalog, ...] = (
    BASE_MAP_EXPORT_CATALOG,
    SCORES_EXPORT_CATALOG,
    CONNECTIONS_EXPORT_CATALOG,
    STELLAR_CARTOGRAPHY_EXPORT_CATALOG,
)


def _validate_export_registry(
    catalogs: tuple[AnalyticExportCatalog, ...],
    *,
    catalog_ids: set[str],
    role: str,
) -> dict[str, AnalyticExportCatalog]:
    by_id: dict[str, AnalyticExportCatalog] = {}
    for export_catalog in catalogs:
        analytic_id = export_catalog.analytic_id
        if not analytic_id:
            raise RuntimeError(f"{role} export catalog must set analytic_id")
        if analytic_id in by_id:
            raise RuntimeError(f"Duplicate export catalog id: {analytic_id!r}")
        if export_catalog.is_empty and export_catalog.analytic_id != analytic_id:
            raise RuntimeError(
                f"Export catalog {analytic_id!r} is_empty flag inconsistent with analytic_id"
            )
        by_id[analytic_id] = export_catalog
    missing = sorted(catalog_ids - set(by_id))
    extra = sorted(set(by_id) - catalog_ids)
    if missing or extra:
        raise RuntimeError(
            f"Turn analytic catalog and {role} export registry are out of sync: "
            f"catalog without export={missing!r}, export without catalog={extra!r}"
        )
    return by_id


_CATALOG_IDS = {entry.id for entry in TURN_ANALYTIC_CATALOG}

EXPORT_REGISTRY: dict[str, AnalyticExportCatalog] = _validate_export_registry(
    _PRODUCTION_EXPORT_CATALOGS,
    catalog_ids=_CATALOG_IDS,
    role="production",
)


def merge_export_registry(
    *extra_catalogs: AnalyticExportCatalog,
) -> dict[str, AnalyticExportCatalog]:
    """Return production registry plus test-only catalogs (overrides allowed)."""
    merged = dict(EXPORT_REGISTRY)
    for export_catalog in extra_catalogs:
        merged[export_catalog.analytic_id] = export_catalog
    return merged
