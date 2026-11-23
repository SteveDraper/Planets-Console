"""Per-analytic hook around planning a fresh submission root.

A registration may open a root plan for each submission of its analytic. The
orchestrator holds it open while it fills dependency-chain turns and plans
the DAG, and offers it the plan before registering anything. Every node the
submission registers carries the root plan's submission open. A submission
that joins in-flight work offers no plan. The orchestrator opens and closes
the hook outside its lock. It offers the plan under its lock, in the hold that
then registers it, so no node of the plan exists before ``accept_plan``
returns, and a root plan that raises leaves the orchestrator unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from api.compute.submission_open import SubmissionOpen

if TYPE_CHECKING:
    from api.analytics.export_context import AnalyticQueryContext
    from api.compute.dag import PlannedComputeNode
    from api.compute.scope import ComputeScope


class RootPlan(Protocol):
    """One open root plan for a submission."""

    @property
    def submission_open(self) -> SubmissionOpen:
        """The open every node this submission registers carries."""
        ...

    def accept_plan(self, planned: tuple[PlannedComputeNode, ...]) -> None:
        """Accept ``planned`` (possibly empty) for a fresh root, before it is registered.

        Runs under the orchestrator lock, after the plan is decided and before
        any of it is registered. It may write durable state and must not call
        back into the orchestrator. Raising refuses the submission: nothing is
        registered and the error reaches the submitter.
        """


OpenRootPlanFn = Callable[
    ["ComputeScope", SubmissionOpen, "AnalyticQueryContext"],
    AbstractContextManager[RootPlan],
]


@dataclass(frozen=True)
class IgnoredRootPlan:
    """A root plan that keeps the submission's open and does nothing on register."""

    submission_open: SubmissionOpen

    def accept_plan(self, planned: tuple[PlannedComputeNode, ...]) -> None:
        return None


def open_ignored_root_plan(
    scope: ComputeScope,
    submission_open: SubmissionOpen,
    ctx: AnalyticQueryContext,
) -> AbstractContextManager[RootPlan]:
    """Default hook: the analytic does nothing around its root plan."""
    return nullcontext(IgnoredRootPlan(submission_open))
