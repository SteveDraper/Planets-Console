"""Pending work records shared by submission and step-execution mixins.

Accepted under the orchestrator lock; executed only after release so job-wire
builders and pool submit never nest under the condition.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.profile import ComputeStepSpec
from api.compute.registry import AnalyticComputeRegistration
from api.compute.wire import DependencyOutputs

__all__ = [
    "PendingInlineExecution",
    "PendingPoolSubmission",
]


@dataclass(frozen=True)
class PendingInlineExecution:
    """Inline work accepted under the orchestrator lock; executed after release.

    Job-wire builders (e.g. scores ``ensure_scores_export``) may take other locks
    such as the inference scheduler lock. Building or running them while holding
    the orchestrator lock deadlocks with scheduler paths that call back into
    dispatch / observer registration.
    """

    node: ComputeNodeRun
    registration: AnalyticComputeRegistration
    step: ComputeStepSpec
    dependency_outputs: DependencyOutputs


@dataclass(frozen=True)
class PendingPoolSubmission:
    """Pool work accepted under the orchestrator lock; built and submitted after release."""

    node: ComputeNodeRun
    registration: AnalyticComputeRegistration
    step: ComputeStepSpec
    dependency_outputs: DependencyOutputs
