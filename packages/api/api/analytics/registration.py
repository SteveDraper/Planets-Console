"""Core turn analytic registration objects."""

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.compute_context import AnalyticComputeContext
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import TurnInfo


@dataclass(frozen=True)
class EmptyExportCatalog:
    """Placeholder export catalog until analytic exports land (#95)."""


EMPTY_EXPORT_CATALOG = EmptyExportCatalog()

TurnAnalyticHandler = Callable[[AnalyticComputeContext], dict]


def handler_from_turn_and_options(
    fn: Callable[[TurnInfo, TurnAnalyticsOptions], dict],
) -> TurnAnalyticHandler:
    return lambda ctx: fn(ctx.turn, ctx.options)


def handler_from_turn(fn: Callable[[TurnInfo], dict]) -> TurnAnalyticHandler:
    return lambda ctx: fn(ctx.turn)


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
