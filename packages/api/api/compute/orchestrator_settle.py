"""Settling in-flight work, and aborting one node, for ComputeOrchestrator.

A settle applies a caller's policy to the non-terminal nodes its work
selection names, all in one orchestrator lock hold. It never drains post-lock
callbacks; the caller owns that drain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.compute.dag_reach import needed_scopes
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


class OrchestratorSettleMixin:
    """Settle in-flight work; abort one node."""

    def settle_in_flight_work(
        self: ComputeOrchestrator,
        work: InFlightWork,
        policy: InFlightSettlePolicy,
    ) -> None:
        """Apply ``policy`` to every non-terminal node ``work`` selects.

        A running node takes ``policy.running``; any other non-terminal node
        takes ``policy.unstarted``. ``FINISH_WITHOUT_STAMP`` raises the node's
        ``running_step``, so its worker finishes and the execution then ends
        without persisting or stamping. ``DISCARD`` fails the node with
        ``DiscardedWorkRefused``, unless non-terminal work this settle leaves
        alive still needs it: such a node is kept.

        Runs under the orchestrator lock and does not drain the post-lock
        callbacks it queues.
        """
        with self._condition:
            discards: list[ComputeNodeRun] = []
            for scope, node in self._nodes_in(work):
                if node.is_terminal:
                    continue
                candidate = InFlightCandidate(scope=scope, submission_open=node.submission_open)
                if node.state == "running":
                    if policy.running(candidate) is RunningDisposition.FINISH_WITHOUT_STAMP:
                        node.running_step = max(
                            node.running_step,
                            RunningStepDisposition.FINISH_WITHOUT_STAMP,
                        )
                elif policy.unstarted(candidate) is UnstartedDisposition.DISCARD:
                    discards.append(node)
            if not discards:
                return
            discarded = {node.scope for node in discards}
            needed = needed_scopes(
                self._nodes,
                (scope for scope in self._nodes if scope not in discarded),
            )
            for node in discards:
                if node.scope in needed:
                    continue
                self._fail_node(
                    node,
                    DiscardedWorkRefused(
                        "in-flight work was discarded before it started executing"
                    ),
                )

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
            self._abort_node_locked(node, error)
        self._observers.drain_post_lock_callbacks()
        return True

    def _abort_node_locked(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        error: BaseException,
    ) -> None:
        """Fail non-terminal ``node`` with ``error`` and record the abort. Caller holds the lock.

        A running node also records its step as finished ``failed``. Nothing
        is drained.
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
                "reason": "abort_scope",
                "priorState": prior_state,
                "priorProfileStepIndex": node.profile_step_index,
                "wasRunning": was_running,
                "errorType": type(error).__name__,
            },
        )
        self._fail_node(node, error)
