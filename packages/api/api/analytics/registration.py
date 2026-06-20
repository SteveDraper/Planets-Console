"""Core turn analytic registration objects."""

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.exports.catalog import AnalyticExportCatalog

TurnAnalyticHandler = Callable[[AnalyticComputeContext], dict]


@dataclass(frozen=True)
class TurnAnalyticRegistration:
    """One turn analytic: catalog metadata, context handler, and export catalog."""

    catalog_entry: TurnAnalyticCatalogEntry
    compute: TurnAnalyticHandler
    export_catalog: AnalyticExportCatalog


_VALID_ANALYTIC_TYPES = frozenset({"base", "selectable"})


def _require_non_empty_string(value: str, *, field: str, analytic_id: str | None = None) -> None:
    if value and value.strip():
        return
    prefix = f"Turn analytic {analytic_id!r} " if analytic_id is not None else "Turn analytic "
    raise RuntimeError(f"{prefix}catalog entry {field} must be a non-empty string, got {value!r}")


def validate_turn_analytic_registrations(
    registrations: tuple[TurnAnalyticRegistration, ...],
) -> None:
    """Fail at import when registrations are incomplete or duplicate ids."""
    if not registrations:
        raise RuntimeError("Turn analytic registrations must not be empty.")
    seen_ids: set[str] = set()
    for registration in registrations:
        entry = registration.catalog_entry
        analytic_id = entry.id
        _require_non_empty_string(analytic_id, field="id")
        if analytic_id in seen_ids:
            raise RuntimeError(f"Duplicate turn analytic registration id: {analytic_id!r}")
        seen_ids.add(analytic_id)
        _require_non_empty_string(entry.name, field="name", analytic_id=analytic_id)
        if entry.type not in _VALID_ANALYTIC_TYPES:
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} catalog entry type must be 'base' or "
                f"'selectable', got {entry.type!r}"
            )
        if not entry.supports_table and not entry.supports_map:
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} must support at least one of table or map view"
            )
        if not callable(registration.compute):
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} compute must be callable, "
                f"got {type(registration.compute).__name__}"
            )
        export_analytic_id = registration.export_catalog.analytic_id
        if export_analytic_id != analytic_id:
            raise RuntimeError(
                f"Turn analytic {analytic_id!r} export catalog analytic_id must match "
                f"catalog entry id, got {export_analytic_id!r}"
            )
