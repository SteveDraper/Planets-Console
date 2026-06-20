"""Compute-time context passed into Core turn analytic handlers."""

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.options import TurnAnalyticsOptions
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.models.game import TurnInfo


@dataclass(frozen=True)
class AnalyticComputeContext:
    """Cross-cutting inputs for one turn analytic compute invocation.

    Handlers read ``diagnostics`` from ``ctx.diagnostics``, not from
    ``ctx.options.diagnostics``. Dispatch sets both fields to the same object; routers
    and services pass diagnostics through ``TurnAnalyticsOptions``.
    """

    turn: TurnInfo
    options: TurnAnalyticsOptions
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS
    query: AnalyticQueryContext | None = None


def make_analytic_compute_context(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
    *,
    load_turn: Callable[[int], TurnInfo | None] | None = None,
) -> AnalyticComputeContext:
    """Build dispatch context; mirrors diagnostics from options when present."""
    resolved = options or TurnAnalyticsOptions()
    return AnalyticComputeContext(
        turn=turn,
        options=resolved,
        diagnostics=resolved.diagnostics,
        query=make_analytic_query_context(turn, resolved, load_turn=load_turn),
    )


def invoke_analytic_compute(
    compute: Callable[[AnalyticComputeContext], dict],
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
    *,
    load_turn: Callable[[int], TurnInfo | None] | None = None,
) -> dict:
    """Run a context-first compute handler for tests and direct callers."""
    return compute(make_analytic_compute_context(turn, options, load_turn=load_turn))
