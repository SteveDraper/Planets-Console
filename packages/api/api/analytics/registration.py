"""Core turn analytic registration objects."""

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.compute_context import AnalyticComputeContext


@dataclass(frozen=True)
class EmptyExportCatalog:
    """Placeholder export catalog until analytic exports land (#95)."""


EMPTY_EXPORT_CATALOG = EmptyExportCatalog()

TurnAnalyticHandler = Callable[[AnalyticComputeContext], dict]


@dataclass(frozen=True)
class TurnAnalyticRegistration:
    """One turn analytic: catalog metadata, compute handler, and export catalog."""

    catalog_entry: TurnAnalyticCatalogEntry
    handler: TurnAnalyticHandler
    export_catalog: EmptyExportCatalog = EMPTY_EXPORT_CATALOG


def validate_turn_analytic_registrations(
    registrations: tuple[TurnAnalyticRegistration, ...],
) -> None:
    """Fail at import when registrations are incomplete or duplicate ids."""
    if not registrations:
        raise RuntimeError("Turn analytic registrations must not be empty.")
    seen_ids: set[str] = set()
    for registration in registrations:
        analytic_id = registration.catalog_entry.id
        if analytic_id in seen_ids:
            raise RuntimeError(f"Duplicate turn analytic registration id: {analytic_id!r}")
        seen_ids.add(analytic_id)
        if registration.handler is None:
            raise RuntimeError(
                f"Turn analytic registration {analytic_id!r} is missing a compute handler."
            )
