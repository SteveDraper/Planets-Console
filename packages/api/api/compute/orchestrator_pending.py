"""Pending work records shared by submission and step-execution mixins.

A dispatch pass commits each record under the orchestrator lock, in the same
hold that marks its node ``running``. The records run only after release, so
job-wire builders and pool submit never nest under the condition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.profile import ComputeStepSpec
from api.compute.registry import AnalyticComputeRegistration
from api.compute.wire import BuildStepJobWireKwargs

__all__ = [
    "DispatchedWork",
    "PendingInlineExecution",
    "PendingPoolSubmission",
    "PendingStep",
]


@dataclass(eq=False)
class PendingStep:
    """One step attempt a dispatch pass committed: its node, step and builder inputs.

    ``is_handed_on`` turns True, under the orchestrator lock, once the
    attempt is handed on: an inline finish has started to apply, or the pool
    submitter returned, which means the pool accepted the item. After that
    the attempt's outcome belongs to that finish or to the pool, so a later
    failure of this record must not touch the node. The flag covers only what
    escapes the finish's own containment: a raise while an inline finish
    applies fails a still-running execution in that same hold. An epoch
    retry of the same step keeps the execution generation and step index, so
    this flag, not those, tells this attempt from a retry.
    """

    node: ComputeNodeRun
    registration: AnalyticComputeRegistration
    step: ComputeStepSpec
    job_wire_kwargs: BuildStepJobWireKwargs
    # The node execution this attempt was dispatched for.
    execution_generation: int
    is_handed_on: bool = False


@dataclass(eq=False)
class PendingInlineExecution(PendingStep):
    """Inline work committed under the orchestrator lock; executed after release.

    Job-wire builders (e.g. scores ``admit_scores_export_work``) may take other locks
    such as the inference scheduler lock. Building or running them while holding
    the orchestrator lock deadlocks with scheduler paths that call back into
    dispatch / observer registration.
    """


@dataclass(eq=False)
class PendingPoolSubmission(PendingStep):
    """Pool work committed under the orchestrator lock; submitted after release.

    Its job wire is built later, on the pool worker that picks it.
    """


@dataclass
class DispatchedWork:
    """The step attempts one dispatch pass committed, in commit order.

    The pass appends each record in the hold that marks its node ``running``,
    so a raise later in the pass still leaves every committed record here for
    the hand-off. A pass submits at most one pool step today; ``pool`` is a
    list so the hand-off does not encode that rule.
    """

    inline: list[PendingInlineExecution] = field(default_factory=list)
    pool: list[PendingPoolSubmission] = field(default_factory=list)
