"""Validate ensure_dependency edges against an export catalog registry."""

from __future__ import annotations

from api.analytics.export_types import EnsureDependency
from api.analytics.exports.catalog import AnalyticExportCatalog


def validate_ensure_dependency_targets(
    by_id: dict[str, AnalyticExportCatalog],
    *,
    role: str,
) -> None:
    for catalog in by_id.values():
        if catalog.is_empty:
            continue
        for dependency in catalog.ensure_dependencies:
            validate_ensure_dependency_target(
                catalog.analytic_id,
                dependency,
                by_id,
                role=role,
            )


def validate_ensure_dependency_target(
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
