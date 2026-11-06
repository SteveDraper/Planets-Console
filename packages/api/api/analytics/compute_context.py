"""Compute-time context passed into Core turn analytic handlers."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from api.analytics.export_context import (
    AnalyticQueryContext,
    backfill_earlier_turns_disabled,
    make_analytic_query_context,
)
from api.analytics.options import TurnAnalyticsOptions
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.models.game import TurnInfo
from api.storage.base import StorageBackend


@dataclass(frozen=True)
class AnalyticComputeContext:
    """Cross-cutting inputs for one turn analytic compute invocation.

    Handlers read ``diagnostics`` from ``ctx.diagnostics``, not from
    ``ctx.options.diagnostics``. Dispatch sets both fields to the same object; routers
    and services pass diagnostics through ``TurnAnalyticsOptions``.
    """

    turn: TurnInfo
    options: TurnAnalyticsOptions
    exports: AnalyticQueryContext
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS


def _backfill_reader_for_export_services(
    export_services: Mapping[str, object] | None,
) -> Callable[[int], bool]:
    """Reader for a compute context built from export service bundles.

    A fleet bundle reads the game record through its storage. A context with
    no fleet bundle has no record, so the choice is off.
    """
    if export_services:
        from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
        from api.analytics.fleet.injected_services import FleetComputeServices

        fleet = export_services.get(FLEET_ANALYTIC_ID)
        if isinstance(fleet, FleetComputeServices):
            return fleet.persistence.backfill_earlier_turns_enabled
    return backfill_earlier_turns_disabled


def make_analytic_compute_context(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
    *,
    game_id: int,
    perspective: int,
    load_turn: Callable[[int], TurnInfo | None] | None = None,
    export_services: Mapping[str, object] | None = None,
    ensure_turn: Callable[[int], TurnInfo | None] | None = None,
    read_backfill_earlier_turns: Callable[[int], bool] | None = None,
    storage: StorageBackend | None = None,
) -> AnalyticComputeContext:
    """Build dispatch context; mirrors diagnostics from options when present."""
    resolved = options or TurnAnalyticsOptions()
    if read_backfill_earlier_turns is None and storage is None:
        read_backfill_earlier_turns = _backfill_reader_for_export_services(export_services)
    return AnalyticComputeContext(
        turn=turn,
        options=resolved,
        diagnostics=resolved.diagnostics,
        exports=make_analytic_query_context(
            turn,
            resolved,
            game_id=game_id,
            perspective=perspective,
            load_turn=load_turn,
            export_services=export_services,
            ensure_turn=ensure_turn,
            read_backfill_earlier_turns=read_backfill_earlier_turns,
            storage=storage,
        ),
    )


def invoke_analytic_compute(
    compute: Callable[[AnalyticComputeContext], dict],
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
    *,
    game_id: int,
    perspective: int,
    load_turn: Callable[[int], TurnInfo | None] | None = None,
    export_services: Mapping[str, object] | None = None,
    ensure_turn: Callable[[int], TurnInfo | None] | None = None,
    read_backfill_earlier_turns: Callable[[int], bool] | None = None,
    storage: StorageBackend | None = None,
) -> dict:
    """Run a context-first compute handler for tests and direct callers."""
    return compute(
        make_analytic_compute_context(
            turn,
            options,
            game_id=game_id,
            perspective=perspective,
            load_turn=load_turn,
            export_services=export_services,
            ensure_turn=ensure_turn,
            read_backfill_earlier_turns=read_backfill_earlier_turns,
            storage=storage,
        )
    )
