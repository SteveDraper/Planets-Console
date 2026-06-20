"""Aggregate export catalogs and validate against turn analytic catalog."""

from __future__ import annotations

from api.analytics.catalog import TURN_ANALYTIC_CATALOG
from api.analytics.export_types import EnsureDependency
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.registry import TURN_ANALYTIC_REGISTRATIONS


def _validate_ensure_dependency_targets(
    by_id: dict[str, AnalyticExportCatalog],
    *,
    role: str,
) -> None:
    for catalog in by_id.values():
        if catalog.is_empty:
            continue
        for dependency in catalog.ensure_dependencies:
            _validate_ensure_dependency_target(
                catalog.analytic_id,
                dependency,
                by_id,
                role=role,
            )


def _validate_ensure_dependency_target(
    declaring_analytic_id: str,
    dependency: EnsureDependency,
    by_id: dict[str, AnalyticExportCatalog],
    *,
    role: str,
) -> None:
    target = by_id.get(dependency.analytic_id)
    if target is None:
        raise RuntimeError(
            f"{role} export catalog {declaring_analytic_id!r} "
            f"ensure_dependencies references missing analytic_id "
            f"{dependency.analytic_id!r}"
        )
    if target.is_empty:
        raise RuntimeError(
            f"{role} export catalog {declaring_analytic_id!r} "
            f"ensure_dependencies references empty catalog "
            f"{dependency.analytic_id!r}"
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
        by_id[analytic_id] = export_catalog
    missing = sorted(catalog_ids - set(by_id))
    extra = sorted(set(by_id) - catalog_ids)
    if missing or extra:
        raise RuntimeError(
            f"Turn analytic catalog and {role} export registry are out of sync: "
            f"catalog without export={missing!r}, export without catalog={extra!r}"
        )
    _validate_ensure_dependency_targets(by_id, role=role)
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
    return merged
