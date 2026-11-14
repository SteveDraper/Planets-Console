"""Settling in-flight work, and aborting one node, for ComputeOrchestrator.

A settle applies a caller's policy to the non-terminal nodes its work
selection names, all in one orchestrator lock hold. It never drains post-lock
callbacks. They share one queue, so the caller's drain, or another thread's
drain that runs first, applies them. ``drain_post_lock_callbacks`` is the
public drain for a caller with no drain of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, TypeAlias

from api.compute.dag_reach import needed_scopes
from api.compute.errors import ComputeScopeAbortedError
from api.compute.in_flight_settle import (
    InFlightCandidate,
    InFlightSettlePolicy,
    InFlightWork,
    RunningDisposition,
    UnstartedDisposition,
)
from api.compute.running_step import RunningStepDisposition
from api.exceptions import DiscardedWorkRefused

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator
    from api.compute.orchestrator_state import ComputeNodeRun
    from api.compute.scope import ComputeScope


_AbortReason: TypeAlias = Literal["abort_scope", "settle"]


class _Ending(Enum):
    """How a settle ends a node it does not keep."""

    DISCARD = "discard"
    ABORT = "abort"


_UNSTARTED_ENDING: Mapping[UnstartedDisposition, _Ending] = MappingProxyType(
    {UnstartedDisposition.DISCARD: _Ending.DISCARD, UnstartedDisposition.ABORT: _Ending.ABORT}
)
_RUNNING_ENDING: Mapping[RunningDisposition, _Ending] = MappingProxyType(
    {RunningDisposition.ABORT: _Ending.ABORT}
)
_RUNNING_STEP_RAISED_TO: Mapping[RunningDisposition, RunningStepDisposition] = MappingProxyType(
    {
        RunningDisposition.FINISH_WITHOUT_STAMP: RunningStepDisposition.FINISH_WITHOUT_STAMP,
        RunningDisposition.END_AFTER_STEP: RunningStepDisposition.END_AFTER_STEP,
    }
)


class OrchestratorSettleMixin:
    """Settle in-flight work, drain what it queued, and abort one node."""

    def settle_in_flight_work(
        self: ComputeOrchestrator,
        work: InFlightWork,
        policy: InFlightSettlePolicy,
    ) -> None:
        """Apply ``policy`` to every non-terminal node ``work`` selects.

        A running node takes ``policy.running``; any other non-terminal node
        takes ``policy.unstarted``. ``FINISH_WITHOUT_STAMP`` and
        ``END_AFTER_STEP`` raise the node's ``running_step``; the start-or-requeue
        gate then re-derives "needed" for ``END_AFTER_STEP`` each time it asks.
        ``DISCARD`` fails the node with ``DiscardedWorkRefused`` and ``ABORT``
        aborts it with ``ComputeScopeAbortedError``, unless work this settle
        leaves alive still needs it (``needed_scopes``): such a node is kept.

        Runs under the orchestrator lock and does not drain the post-lock
        callbacks it queues; another thread's drain may run them before the
        caller's.
        """
        with self._condition:
            endings: list[tuple[ComputeNodeRun, _Ending]] = []
            for scope, node in self._nodes_in(work):
                if node.is_terminal:
                    continue
                candidate = InFlightCandidate(scope=scope, submission_open=node.submission_open)
                if node.state == "running":
                    running = policy.running(candidate)
                    raised_to = _RUNNING_STEP_RAISED_TO.get(running)
                    if raised_to is not None:
                        node.running_step = max(node.running_step, raised_to)
                    ending = _RUNNING_ENDING.get(running)
                else:
                    ending = _UNSTARTED_ENDING.get(policy.unstarted(candidate))
                if ending is not None:
                    endings.append((node, ending))
            if not endings:
                return
            ended = {node.scope for node, _ending in endings}
            needed = needed_scopes(
                self._nodes,
                (scope for scope in self._nodes if scope not in ended),
            )
            for node, ending in endings:
                if node.scope in needed:
                    continue
                match ending:
                    case _Ending.DISCARD:
                        self._fail_node(
                            node,
                            DiscardedWorkRefused(
                                "in-flight work was discarded before it started executing"
                            ),
                        )
                    case _Ending.ABORT:
                        self._abort_node_locked(
                            node,
                            ComputeScopeAbortedError("in-flight work was aborted by a settle"),
                            reason="settle",
                        )

    def drain_post_lock_callbacks(self: ComputeOrchestrator) -> None:
        """Run the post-lock work queued so far, including what a settle queued.

        A settle does not drain. A caller that settles outside a drain of its
        own runs this afterwards, for example off the response path of the
        request that settled.
        """
        self._observers.drain_post_lock_callbacks()

    def abort_scope(
        self: ComputeOrchestrator,
        scope: ComputeScope,
        error: BaseException,
        *,
        expected_execution_generation: int | None = None,
    ) -> bool:
        """Abort a non-terminal node so a later ``force_fresh`` submit can replace it.

        Returns whether a node was aborted. No-op when the scope is absent or already
        terminal, or when it is no longer the expected execution generation. Used when
        a stream row run is cancelled while orchestrator work for that scope is still
        in flight.

        Prefer :class:`ComputeScopeAbortedError` for intentional cancels: the node
        becomes ``failed`` for force_fresh replacement, but dependents do **not**
        cascade-fail (they stay ``waiting_deps`` on the singleton DAG). Abort
        itself does not recreate those dependencies. A later ``force_fresh``
        attach of a ``waiting_deps`` waiter recreates abort-failed dependencies
        along the ``waiting_deps`` chain.
        """
        with self._condition:
            node = self._nodes.get(scope)
            if node is None or node.is_terminal:
                return False
            if (
                expected_execution_generation is not None
                and node.execution_generation != expected_execution_generation
            ):
                return False
            self._abort_node_locked(node, error, reason="abort_scope")
        self._observers.drain_post_lock_callbacks()
        return True

    def _abort_node_locked(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        error: BaseException,
        *,
        reason: _AbortReason,
    ) -> None:
        """Fail non-terminal ``node`` with ``error`` and record the abort. Caller holds the lock.

        ``reason`` names the caller in the ``abort`` lifecycle record. A running
        node also records its step as finished ``failed``. Nothing is drained.
        """
        prior_state = node.state
        was_running = prior_state == "running"
        finished_step_kind: str | None = None
        finished_step_index = node.step_index
        if was_running:
            registration = self._compute_registry.get(node.scope.analytic_id)
            if registration is not None:
                finished_step_kind = self._current_step_spec(node, registration).step_kind
                self._observers.notify_step_complete(
                    node,
                    finished_step_kind,
                    step_index=finished_step_index,
                    surface="pool",
                    terminal_state="failed",
                )
        self._observers.notify_lifecycle(
            "abort",
            node.scope,
            execution_generation=node.execution_generation,
            node=node,
            step_kind=finished_step_kind,
            step_index=finished_step_index,
            detail={
                "reason": reason,
                "priorState": prior_state,
                "priorProfileStepIndex": node.profile_step_index,
                "wasRunning": was_running,
                "errorType": type(error).__name__,
            },
        )
        self._fail_node(node, error)
