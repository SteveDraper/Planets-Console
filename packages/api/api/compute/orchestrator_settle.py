"""Settling in-flight work, and aborting one node, for ComputeOrchestrator.

A settle applies a caller's policy to the non-terminal nodes its work
selection names, all in one orchestrator lock hold. It never drains post-lock
callbacks. They share one queue, so the caller's drain, another thread's
drain that runs first, or the drain already active on the caller's thread
applies them. ``drain_post_lock_callbacks`` is the public drain for a caller
with no drain of its own, and ``run_after_root_plans`` runs a caller's work
after that drain once no root plan is open on its thread.
"""

from __future__ import annotations

from collections.abc import Callable
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

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator
    from api.compute.orchestrator_state import ComputeNodeRun
    from api.compute.scope import ComputeScope


_AbortReason: TypeAlias = Literal["abort_scope", "settle"]


class OrchestratorSettleMixin:
    """Settle in-flight work, drain what it queued, run work after root plans, abort one node."""

    def settle_in_flight_work(
        self: ComputeOrchestrator,
        work: InFlightWork,
        policy: InFlightSettlePolicy,
        *,
        then: Callable[[], None] | None = None,
    ) -> frozenset[ComputeScope]:
        """Apply ``policy`` to every non-terminal node ``work`` selects; return what it stopped.

        A running node takes ``policy.running``; any other non-terminal node
        takes ``policy.unstarted``. ``END_AFTER_STEP`` raises the node's
        ``running_step``; the start-or-requeue gate then re-derives "needed"
        each time it asks. ``ABORT`` aborts the node with
        ``ComputeScopeAbortedError``, unless work this settle leaves alive
        still needs it (``needed_scopes``): such a node is kept.

        The returned scopes are the nodes this settle stopped: those it ended,
        and the running ones whose ``running_step`` it raised and that no
        kept work needs. A node kept because kept work needs it is not
        returned.

        ``then`` runs after the settle, in the same orchestrator lock hold,
        whether or not anything was stopped. No plan can register between the
        settle and what ``then`` publishes. It must not call back into the
        orchestrator from another thread or wait on one that does.

        Runs under the orchestrator lock and does not drain the post-lock
        callbacks it queues; another thread's drain may run them before the
        caller's.
        """
        with self._condition:
            stopped = self._settle_locked(work, policy)
            if then is not None:
                then()
            return stopped

    def _settle_locked(
        self: ComputeOrchestrator,
        work: InFlightWork,
        policy: InFlightSettlePolicy,
    ) -> frozenset[ComputeScope]:
        """The body of :meth:`settle_in_flight_work`. Caller holds the lock."""
        aborts: list[ComputeNodeRun] = []
        limited: list[ComputeScope] = []
        for scope, node in self._nodes_in(work):
            if node.is_terminal:
                continue
            candidate = InFlightCandidate(scope=scope, submission_open=node.submission_open)
            if node.state != "running":
                if policy.unstarted(candidate) is UnstartedDisposition.ABORT:
                    aborts.append(node)
                continue
            match policy.running(candidate):
                case RunningDisposition.ABORT:
                    aborts.append(node)
                case RunningDisposition.END_AFTER_STEP:
                    node.running_step = RunningStepDisposition.END_AFTER_STEP
                    limited.append(scope)
                case RunningDisposition.KEEP:
                    pass
        if not aborts and not limited:
            return frozenset()
        aborting = {node.scope for node in aborts}
        needed = needed_scopes(
            self._nodes,
            (scope for scope in self._nodes if scope not in aborting),
        )
        stopped = {scope for scope in limited if scope not in needed}
        for node in aborts:
            if node.scope in needed:
                continue
            stopped.add(node.scope)
            self._abort_node_locked(
                node,
                ComputeScopeAbortedError("in-flight work was aborted by a settle"),
                reason="settle",
            )
        return frozenset(stopped)

    def drain_post_lock_callbacks(self: ComputeOrchestrator) -> None:
        """Run the post-lock work queued so far, including what a settle queued.

        A settle does not drain. A caller that settles outside a drain of its
        own runs this afterwards, for example off the response path of the
        request that settled. Called on a thread that is already draining this
        orchestrator's queue, for example from a persist callback, it returns
        at once and that drain runs the work after the current callback.
        """
        self._observers.drain_post_lock_callbacks()

    def run_after_root_plans(self: ComputeOrchestrator, callback: Callable[[], None]) -> None:
        """Run ``callback`` once no root-plan block of this orchestrator is open on this thread.

        At once after a drain when none is open, else held for the outermost
        block's exit on this thread; a failure is contained and logged
        either way (``OrchestratorObservers.run_after_root_plans``).
        """
        self._observers.run_after_root_plans(callback)

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

        Drains the abort's listeners before returning; :meth:`queue_scope_abort`
        is the same abort with the drain left to the caller.
        """
        aborted = self.queue_scope_abort(
            scope, error, expected_execution_generation=expected_execution_generation
        )
        if aborted:
            self._observers.drain_post_lock_callbacks()
        return aborted

    def queue_scope_abort(
        self: ComputeOrchestrator,
        scope: ComputeScope,
        error: BaseException,
        *,
        expected_execution_generation: int | None = None,
    ) -> bool:
        """Abort a non-terminal node under the lock and queue its listeners, draining nothing.

        Same no-op rules and return value as :meth:`abort_scope`. Plans,
        submits and drains nothing, so it is safe inside an open root plan;
        the queued listeners run at the next drain on any thread.
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
                finished_step = self._current_step_spec(node, registration)
                finished_step_kind = finished_step.step_kind
                self._observers.notify_step_complete(
                    node,
                    finished_step_kind,
                    step_index=finished_step_index,
                    surface=finished_step.surface,
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
