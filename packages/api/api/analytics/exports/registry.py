"""Aggregate export catalogs and validate against turn analytic catalog."""

from __future__ import annotations

from api.analytics.catalog import TURN_ANALYTIC_CATALOG
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.ensure_validation import validate_ensure_dependency_targets
from api.analytics.registry import TURN_ANALYTIC_REGISTRATIONS


def validate_export_catalogs(
    catalogs: tuple[AnalyticExportCatalog, ...],
    *,
    catalog_ids: set[str],
    role: str,
) -> dict[str, AnalyticExportCatalog]:
    """Validate export catalogs against the turn analytic catalog and ensure wiring."""
    return _validate_export_registry(catalogs, catalog_ids=catalog_ids, role=role)


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
        by_id[analytic_id] = export_catalog
    missing = sorted(catalog_ids - set(by_id))
    extra = sorted(set(by_id) - catalog_ids)
    if missing or extra:
        raise RuntimeError(
            f"Turn analytic catalog and {role} export registry are out of sync: "
            f"catalog without export={missing!r}, export without catalog={extra!r}"
        )
    validate_ensure_dependency_targets(by_id, role=role)
    return by_id


_CATALOG_IDS = {entry.id for entry in TURN_ANALYTIC_CATALOG}

EXPORT_REGISTRY: dict[str, AnalyticExportCatalog] = _validate_export_registry(
    tuple(registration.export_catalog for registration in TURN_ANALYTIC_REGISTRATIONS),
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
    validate_ensure_dependency_targets(merged, role="merged")
    return merged
