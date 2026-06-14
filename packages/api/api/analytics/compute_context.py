"""Compute-time context passed into Core turn analytic handlers."""

from dataclasses import dataclass

from api.analytics.options import TurnAnalyticsOptions
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.models.game import TurnInfo


class AnalyticQueryContext:
    """Placeholder for the analytic export query context.

    Full type and wiring are specified in ``docs/design-analytic-exports.md`` (planned
    module ``api/analytics/export_context.py``).
    """


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
