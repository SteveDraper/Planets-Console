"""Per-analytic hook around planning a fresh submission root.

A registration may open a root plan for each submission of its analytic. The
orchestrator holds it open while it fills dependency-chain turns and plans
the DAG, and reports the plan it registered. A submission that joins
in-flight work registers no plan. The orchestrator runs the hook outside its
lock and closes it before any selected work runs.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext
    from api.compute.dag import PlannedComputeNode
    from api.compute.scope import ComputeScope
    from api.compute.submission_open import SubmissionOpen


class RootPlan(Protocol):
    """One open root plan for a submission."""

    def plan_registered(self, planned: tuple[PlannedComputeNode, ...]) -> None:
        """The submission registered a fresh root with ``planned`` (possibly empty)."""


OpenRootPlanFn = Callable[
    ["ComputeScope", "SubmissionOpen", "AnalyticQueryContext"],
    AbstractContextManager[RootPlan],
]


class _IgnoredRootPlan:
    def plan_registered(self, planned: tuple[PlannedComputeNode, ...]) -> None:
        return None


IGNORED_ROOT_PLAN: RootPlan = _IgnoredRootPlan()


def open_ignored_root_plan(
    scope: ComputeScope,
    submission_open: SubmissionOpen,
    ctx: AnalyticQueryContext,
) -> AbstractContextManager[RootPlan]:
    """Default hook: the analytic does nothing around its root plan."""
    return nullcontext(IGNORED_ROOT_PLAN)
