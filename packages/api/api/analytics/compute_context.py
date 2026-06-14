"""Compute-time context passed into Core turn analytic handlers."""

from dataclasses import dataclass

from api.analytics.options import TurnAnalyticsOptions
from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics
from api.models.game import TurnInfo


@dataclass(frozen=True)
class AnalyticComputeContext:
    """Cross-cutting inputs for one turn analytic compute invocation."""

    turn: TurnInfo
    options: TurnAnalyticsOptions
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS
    query: None = None
