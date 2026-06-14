"""Compute-time context passed into Core turn analytic handlers."""

from dataclasses import dataclass

from api.analytics.options import TurnAnalyticsOptions
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.models.game import TurnInfo


class AnalyticQueryContext:
    """Placeholder for analytic export query context; replaced in #93."""


@dataclass(frozen=True)
class AnalyticComputeContext:
    """Cross-cutting inputs for one turn analytic compute invocation.

    Handlers should read ``diagnostics`` from this carrier (``ctx.diagnostics``), not
    from ``ctx.options.diagnostics``. Both are set to the same object at dispatch;
    ``options.diagnostics`` remains only so routers and services can pass diagnostics
    through ``TurnAnalyticsOptions`` until that wire path is retired.
    """

    turn: TurnInfo
    options: TurnAnalyticsOptions
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS
    query: AnalyticQueryContext | None = None
