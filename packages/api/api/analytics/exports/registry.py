"""Aggregate export catalogs and validate against turn analytic catalog."""

from __future__ import annotations

from api.analytics.catalog import TURN_ANALYTIC_CATALOG
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.ensure_validation import validate_ensure_dependency_targets
from api.analytics.exports.schema_validation import validate_export_value_schema
from api.analytics.registry import TURN_ANALYTIC_REGISTRATIONS
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID


def _production_export_catalogs() -> tuple[AnalyticExportCatalog, ...]:
    """Resolve registration placeholders to production export catalogs."""
    catalogs: list[AnalyticExportCatalog] = []
    for registration in TURN_ANALYTIC_REGISTRATIONS:
        if registration.catalog_entry.id == SCORES_ANALYTIC_ID:
            from api.analytics.scores.exports import EXPORT_CATALOG as scores_export_catalog

            catalogs.append(scores_export_catalog)
        else:
            catalogs.append(registration.export_catalog)
    return tuple(catalogs)


def validate_export_catalogs(
    catalogs: tuple[AnalyticExportCatalog, ...],
    *,
    catalog_ids: set[str],
    role: str,
) -> dict[str, AnalyticExportCatalog]:
    """Validate export catalogs against the turn analytic catalog and ensure wiring."""
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
    for export_catalog in catalogs:
        if export_catalog.is_empty or export_catalog.value_schema is None:
            continue
        validate_export_value_schema(
            export_catalog.value_schema,
            analytic_id=export_catalog.analytic_id,
        )
    return by_id


_CATALOG_IDS = {entry.id for entry in TURN_ANALYTIC_CATALOG}

EXPORT_REGISTRY: dict[str, AnalyticExportCatalog] = validate_export_catalogs(
    _production_export_catalogs(),
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

    for export_catalog in extra_catalogs:
        if export_catalog.is_empty or export_catalog.value_schema is None:
            continue
        validate_export_value_schema(
            export_catalog.value_schema,
            analytic_id=export_catalog.analytic_id,
        )
    return merged
