"""Lifecycle and terminal-outcome helpers for ComputeOrchestrator.

Owns park, settle (complete/fail/park), post-step success handling, epoch-retry,
persist-deferred recovery, and force_fresh lifecycle detail assembly. Emits
wire-ready scope keys on lifecycle details so listeners need not reconstruct
``ComputeScope`` from dict fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from api.compute.dag_reach import needed_scopes
from api.compute.orchestrator_observers import LifecycleEventKind
from api.compute.orchestrator_state import ComputeNodeRun, ComputeRequest
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
from api.compute.running_step import StepExit
from api.compute.scope import format_compute_scope_key
from api.compute.wire import StepOutcome, coerce_step_result
from api.exceptions import DiscardedWorkRefused

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator
    from api.compute.registry import AnalyticComputeRegistration

# The exit each step outcome takes first once the step has finished.
_STEP_EXIT_BY_OUTCOME: Mapping[StepOutcome, StepExit] = MappingProxyType(
    {
        "persist": StepExit.PERSIST,
        "complete": StepExit.COMPLETE,
        "continue": StepExit.START,
        "park": StepExit.REQUEUE,
        "waiting_deps": StepExit.REQUEUE,
    }
)


class OrchestratorLifecycleMixin:
    """Park, settle, after-step success, epoch-retry, and persist-deferred recovery."""

    def _emit_force_fresh_lifecycle(
        self: ComputeOrchestrator,
        *,
        kind: LifecycleEventKind,
        node: ComputeNodeRun,
        request: ComputeRequest,
    ) -> None:
        """Record force_fresh replace vs attach (caller holds the orchestrator lock)."""
        self._observers.notify_lifecycle(
            kind,
            node.scope,
            execution_generation=node.execution_generation,
            node=node,
            step_index=node.step_index,
            detail={
                "reason": "submit_force_fresh",
                "priorState": node.state,
                "priorProfileStepIndex": node.profile_step_index,
                "wasRunning": node.state == "running",
                "entryStepKind": request.step_kind,
                "priorityBand": node.priority_band,
            },
        )

    def _reset_for_requeue(self: ComputeOrchestrator, node: ComputeNodeRun) -> int:
        """Clear the submit generation so the node can re-enter the dispatch loop.

        Shared by epoch-retry, persist-deferred recovery, and soft park -- the three
        paths that leave an in-flight step and must reopen the node for later work.
        Returns the step index at reset time for lifecycle notifications.
        """
        prior_step_index = node.step_index
        node.generation_at_submit = None
        return prior_step_index

    def _retry_step_after_epoch_bump(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        """Re-queue an epoch-stale step, unless the start-or-requeue gate ends the node."""
        if self._refuse_step_exit(node, StepExit.REQUEUE):
            return
        self._metrics.epoch_discards += 1
        prior_generation = node.generation_at_submit
        current_generation = self._current_invalidation_generation(node)
        prior_step_index = self._reset_for_requeue(node)
        node.state = "ready"
        self._enqueue_ready(node.scope)
        self._observers.notify_ready(node)
        self._observers.notify_lifecycle(
            "epoch_retry",
            node.scope,
            execution_generation=node.execution_generation,
            node=node,
            step_index=prior_step_index,
            detail={
                "reason": "invalidation_generation_bump",
                "priorProfileStepIndex": node.profile_step_index,
                "generationAtSubmit": prior_generation,
                "currentGeneration": current_generation,
            },
        )
        # Never call pool.submit under the orchestrator lock (deadlocks with workers).
        self._observers.schedule_post_lock(self.dispatch_ready_work)

    def _demote_to_waiting_deps(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        """Demote a running node to ``waiting_deps`` without grafting dependencies.

        Soft defer (scores empty tier / non-durable rowComplete, missing RowRun)
        waits for an external ``force_fresh`` / ``wake_scores_scope`` wake -- not
        for another scope to reach ``complete``. Grafting ``node.scope`` onto
        ``dependency_scopes`` would make ``_deps_complete`` require self-complete
        while the node is non-terminal, so force_fresh attach could never promote.
        """
        with self._condition:
            if node.state != "running" or self._refuse_step_exit(node, StepExit.REQUEUE):
                return
            self._reset_for_requeue(node)
            node.error = None
            node.state = "waiting_deps"
            self._dequeue_ready(node.scope)
            self._metrics.epoch_discards += 1

    def _recover_after_persist_deferred(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        recovery: PersistDependencyRecovery,
    ) -> None:
        """Recover onto ``waiting_deps`` and optionally force_fresh a dependency.

        Analytic ``PersistencePolicy.persist`` raises :class:`PersistDeferredError`
        when a durable write cannot complete until a dependency re-closes.
        Failing the node left dependents waiting with no wake for background DAG
        nodes (no table-stream controller). Force-freshing the declared dependency
        reopens the ENSURE edge; when it completes, readiness promotes this node.
        Persist-deferred is a real dependency wait -- not soft ``parked``.

        Graft ``recovery.dependency_scope`` onto ``node.dependency_scopes`` when the
        plan-time ENSURE walk omitted it (e.g. dependency already satisfied when the
        dependent was planned). Without that edge, dependency terminal completion
        never refreshes this node and ``force_fresh_attach`` alone leaves it stuck
        in ``waiting_deps`` (0% CPU hang). Never graft the node's own scope -- that
        self-edge can never become ``complete`` while this node is ``waiting_deps``.
        The force_fresh dependency submit asks for no band of its own: the
        grafted edge gives it this node's band at the next dispatch pass. It
        runs after the lock is released and names this node's execution as its
        requester, so it plans nothing once that execution has ended (aborted
        or replaced) before the plan would be registered. The start-or-requeue
        gate runs first, so a node it ends queues no dependency submit.
        """
        with self._condition:
            if node.state != "running" or self._refuse_step_exit(node, StepExit.REQUEUE):
                return
            prior_step_index = self._reset_for_requeue(node)
            node.error = None
            dependency_scope = recovery.dependency_scope
            if dependency_scope != node.scope and dependency_scope not in node.dependency_scopes:
                node.dependency_scopes = (
                    *node.dependency_scopes,
                    dependency_scope,
                )
            node.state = "waiting_deps"
            self._dequeue_ready(node.scope)
            self._metrics.epoch_discards += 1
            self._observers.notify_lifecycle(
                "persist_deferred",
                node.scope,
                execution_generation=node.execution_generation,
                node=node,
                step_index=prior_step_index,
                detail={
                    "reason": "persist_deferred",
                    "priorProfileStepIndex": node.profile_step_index,
                    "relatedScopeKey": format_compute_scope_key(dependency_scope),
                    "forceFresh": recovery.force_fresh,
                    "dependencyStepKind": recovery.step_kind,
                    "priorityBand": node.priority_band,
                },
            )

            if not recovery.force_fresh:
                return
            dependency_request = ComputeRequest(
                scope=dependency_scope,
                force_fresh=True,
                step_kind=recovery.step_kind,
                bundle=node.bundle,
                submission_open=node.submission_open,
                requester=node.execution_ref,
            )
            self._observers.schedule_post_lock(
                lambda: self._submit_dependencies((dependency_request,))
            )

    def _abandon_persist_if_not_running_or_stale(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        step_exit: StepExit,
    ) -> bool:
        """Return True when the persist leg must not take ``step_exit``. Caller holds the lock."""
        if node.state != "running":
            return True
        if self._refuse_step_exit(node, step_exit):
            return True
        if self._is_epoch_stale(node):
            self._retry_step_after_epoch_bump(node)
            return True
        return False

    def _refuse_step_exit(
        self: ComputeOrchestrator, node: ComputeNodeRun, step_exit: StepExit
    ) -> bool:
        """Fail ``node`` when its running-step disposition does not permit ``step_exit``.

        Returns whether it was refused. "Needed" is derived only when the
        disposition's answer depends on it. Caller holds the lock.

        Asked for ``START`` or ``REQUEUE``, this is the start-or-requeue gate:
        at the pool pick and the thread re-check (``begin_pool_step``), the
        inline post-wire-build re-check, ``_begin_step_execution``, and before
        epoch retry, persist-deferred recovery, soft demotion and park.
        """
        if node.running_step.permits(step_exit, is_needed=lambda: self._is_needed(node)):
            return False
        self._fail_refused_execution(node)
        return True

    def _fail_refused_execution(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        """End an execution its running-step disposition refused. Caller holds the lock.

        It persists nothing further, stamps nothing further and is not
        retried. It fails with its disposition's refusal error.
        """
        self._fail_node(node, node.running_step.refusal_error())

    def _is_needed(self: ComputeOrchestrator, node: ComputeNodeRun) -> bool:
        """Whether other non-terminal work still needs ``node``. Caller holds the lock."""
        others = (scope for scope in self._nodes if scope != node.scope)
        return node.scope in needed_scopes(self._nodes, others)

    def _after_step_success(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        result_wire: object | None,
    ) -> None:
        """Apply a finished step's result. Caller holds the lock.

        The result is read only when it can change the outcome: an execution
        that may take no exit is refused first, and an epoch-stale step is
        re-queued next, whatever it returned, through the start-or-requeue
        gate. Otherwise the outcome names the exit the step takes.
        """
        if node.running_step.permits_no_exit:
            self._fail_refused_execution(node)
            return
        if self._is_epoch_stale(node):
            self._retry_step_after_epoch_bump(node)
            return
        step_result = coerce_step_result(result_wire)
        if self._refuse_step_exit(node, _STEP_EXIT_BY_OUTCOME[step_result.outcome]):
            return

        registration = self._compute_registry[node.scope.analytic_id]
        # Persist runs after this lock is released. Keep generation_at_submit so
        # persist-then-complete can still discard if invalidation lands in that window.
        if step_result.outcome != "persist":
            node.generation_at_submit = None

        if step_result.outcome == "continue":
            if step_result.payload is not None:
                node.result_wire = step_result.payload
            self._continue_node_step(node, registration)
            return

        if step_result.outcome == "park":
            if step_result.payload is not None:
                node.result_wire = step_result.payload
            self._park_node_step(node, reason=step_result.park_reason)
            return

        if step_result.outcome == "waiting_deps":
            if step_result.payload is not None:
                node.result_wire = step_result.payload
            recovery = step_result.wait_recovery
            if recovery is None:
                # Soft defer: demote without PersistDependencyRecovery self-graft.
                def _soft_waiting_deps(
                    deferred_node: ComputeNodeRun = node,
                ) -> None:
                    self._demote_to_waiting_deps(deferred_node)

                self._observers.schedule_post_lock(_soft_waiting_deps)
                return

            def _defer_waiting_deps(
                deferred_node: ComputeNodeRun = node,
                deferred_recovery: PersistDependencyRecovery = recovery,
            ) -> None:
                self._recover_after_persist_deferred(deferred_node, deferred_recovery)

            self._observers.schedule_post_lock(_defer_waiting_deps)
            return

        if step_result.outcome == "persist":
            if step_result.payload is not None:
                node.result_wire = step_result.payload
            elif node.result_wire is None:
                node.result_wire = {}
            self._metrics.persist_calls += 1
            # Persist must not run under the orchestrator lock: fleet refine/scores
            # probes take the inference scheduler lock, and scheduler paths call back
            # into dispatch / observer registration (ABBA deadlock).
            #
            # Ordering invariant (even outside the lock): persist must finish before
            # ``_complete_node``. Completing first would wake dependents / allow
            # ``has_final_ledger`` readers to observe a terminal node whose durable
            # artifact is not written yet (missed overlay, false unsatisfied probes,
            # or skipped scores reschedule decisions). Notifications returned from
            # ``persist`` run only after complete so skip-reschedule sees ``complete``.
            payload = step_result.payload
            persist_then_continue = step_result.persist_then_continue

            def _persist_then_complete(
                completed_node: ComputeNodeRun = node,
                completed_payload: object = payload,
                completed_registration: AnalyticComputeRegistration = registration,
                should_continue: bool = persist_then_continue,
            ) -> None:
                # Cancel/preempt may have aborted this node after the step succeeded
                # but before post-lock persist. Do not persist or complete in that case.
                # Epoch can also advance in this window (durable wipe while persist
                # is queued); do not stamp ``complete`` over a deleted ledger.
                with self._condition:
                    if self._abandon_persist_if_not_running_or_stale(
                        completed_node, StepExit.PERSIST
                    ):
                        return
                ctx = self._ctx_for_node(completed_node)
                try:
                    post_lock_callback = completed_registration.persistence_policy.persist(
                        ctx,
                        completed_node.scope,
                        completed_payload,
                    )
                except BaseException as exc:
                    # Persist runs after step-complete success; a raise must not leave a
                    # ghost ``running`` node (empty queues, freeze ``nothing_steppable``).
                    # Do not re-raise: pool workers call complete_pool_step on this thread
                    # and an escaping exception would kill the worker loop.
                    if isinstance(exc, PersistDeferredError):
                        # Analytic-owned recovery: demote to waiting_deps and optionally
                        # force_fresh the declared dependency (e.g. open scores evidence).
                        self._recover_after_persist_deferred(
                            completed_node,
                            exc.recovery,
                        )
                        return
                    with self._condition:
                        # Epoch refusal from persist. Same split as an epoch that
                        # moved before the hook: an execution a settle left
                        # finishing without a stamp fails, and a running shell or
                        # live turn is re-queued.
                        if isinstance(exc, DiscardedWorkRefused):
                            if self._abandon_persist_if_not_running_or_stale(
                                completed_node, StepExit.PERSIST
                            ):
                                return
                        if completed_node.state == "running":
                            self._fail_node(completed_node, exc)
                    return
                with self._condition:
                    if self._abandon_persist_if_not_running_or_stale(
                        completed_node,
                        StepExit.START if should_continue else StepExit.COMPLETE,
                    ):
                        return
                    if should_continue:
                        self._continue_node_step(completed_node, completed_registration)
                    else:
                        self._complete_node(completed_node)
                    if post_lock_callback is not None:
                        self._observers.schedule_post_lock(post_lock_callback)

            self._observers.schedule_post_lock(_persist_then_complete)
            return

        if step_result.outcome == "complete":
            # Keep a provisional continue payload when the terminal step has none
            # (e.g. scores materialize export tree then tier_solve skip). Fleet
            # persist-deferred can enter scores at tier_solve, so there is no
            # continue payload -- still leave ``{}`` so dependents can dispatch.
            if step_result.payload is not None:
                node.result_wire = step_result.payload
            elif node.result_wire is None:
                node.result_wire = {}
            self._complete_node(node)
            return

        raise RuntimeError(f"unsupported step outcome {step_result.outcome!r}")

    def _continue_node_step(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
    ) -> None:
        node.step_index += 1
        steps = registration.compute_profile.steps
        current_step = steps[node.profile_step_index]
        next_profile_index = node.profile_step_index + 1
        if next_profile_index < len(steps):
            next_step = steps[next_profile_index]
            if next_step.step_kind != current_step.step_kind:
                # Advance profile; retain prior step claims until node terminal so
                # peers cannot rematerialize while this node is still non-terminal.
                node.profile_step_index = next_profile_index
        node.state = "ready"
        self._enqueue_ready(node.scope)
        self._observers.notify_ready(node)
        # Defer dispatch so pool submit is never nested under this lock.
        self._observers.schedule_post_lock(self.dispatch_ready_work)

    def _settle_node(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        *,
        state: Literal["complete", "failed", "parked"],
        error: BaseException | None = None,
    ) -> None:
        """Transition ``node`` out of active dispatch and publish its outcome.

        Caller must hold ``self._condition``. Shared by complete, fail, and park
        -- the three states that stop a node's dispatch loop and report a
        :class:`ScopeLifecycleSnapshot`. Soft park (``state="parked"``) does not
        release waiters (they keep waiting for a real terminal outcome) and does
        not notify dependents (dependents stay blocked rather than promoted); the
        caller emits its own lifecycle event and resets ``generation_at_submit``
        around this call.
        """
        soft_pause = state == "parked"
        node.state = state
        node.error = error
        if not soft_pause:
            node.park_reason = None
        self._dequeue_ready(node.scope)
        if not soft_pause:
            for waiter in node.waiters:
                waiter._waiter_error = error
            node.waiters.clear()
            # Wake orchestration-plane ComputeHandle.wait callers (leaders and
            # attachers). Invariant: ``_settle_node`` always runs while the
            # caller holds ``self._condition`` (non-reentrant), so notify without
            # re-entering the lock.
            self._condition.notify_all()
        self._observers.notify_scope_outcome(node)
        if not soft_pause:
            completed_scope = node.scope
            self._observers.schedule_post_lock(
                lambda: self._handle_dependency_terminal(completed_scope),
            )

    def _complete_node(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        self._settle_node(node, state="complete")

    def _fail_node(self: ComputeOrchestrator, node: ComputeNodeRun, error: BaseException) -> None:
        if node.state == "failed":
            return
        self._settle_node(node, state="failed", error=error)

    def _park_node_step(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        *,
        reason: str | None,
    ) -> None:
        """Park a non-progressing step until an explicit ``force_fresh`` wake.

        Soft park does **not** complete the node (dependents stay blocked), but still
        publishes an immutable outcome snapshot so scores can reattach empty stream
        delivery without unlocking same-turn fleet. Its one caller,
        ``_after_step_success``, has already put the ``park`` outcome's
        ``REQUEUE`` exit through the start-or-requeue gate in this lock hold.
        """
        if node.state != "running":
            return

        prior_step_index = self._reset_for_requeue(node)
        node.park_reason = reason
        self._settle_node(node, state="parked")
        self._observers.notify_lifecycle(
            "step_parked",
            node.scope,
            execution_generation=node.execution_generation,
            node=node,
            step_index=prior_step_index,
            detail={
                "reason": reason or "step_parked",
                "priorProfileStepIndex": node.profile_step_index,
            },
        )

    def _maybe_wake_parked_node(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        """Re-ready a soft-parked node on explicit ``force_fresh`` attach."""
        if node.state != "parked":
            return
        node.park_reason = None
        node.generation_at_submit = None
        if self._deps_complete(node):
            node.state = "ready"
            self._enqueue_ready(node.scope)
            self._observers.notify_ready(node)
        else:
            node.state = "waiting_deps"
            self._dequeue_ready(node.scope)
