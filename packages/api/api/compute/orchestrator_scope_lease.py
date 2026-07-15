"""Process-wide scope lease and satisfaction short-circuit for ComputeOrchestrator.

Owns acquire/park/wake/release, durable-satisfaction short-circuit, and
seal-before-expensive-work so the DAG scheduler stays focused on readiness.
Cross-binding dedupe semantics live in ``scope_lease``; this module is the
orchestrator integration (including post-lock execute paths that must seal).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from api.compute.scope import ComputeScope
from api.compute.scope_lease import ScopeStepClaimKey, get_process_scope_lease

if TYPE_CHECKING:
    from api.compute.orchestrator import (
        ComputeNodeRun,
        _PendingInlineExecution,
        _PendingPoolSubmission,
    )
    from api.compute.profile import ComputeStepSpec
    from api.compute.registry import AnalyticComputeRegistration
    from api.compute.scope_lease import ProcessWideScopeLease


class OrchestratorScopeLeaseMixin:
    """Lease claim lifecycle and satisfaction short-circuit for a compute binding.

    Expects the concrete orchestrator to provide ``_condition``, ``_nodes``,
    ``_metrics``, ``_observers``, ``_compute_registry``, ``_cached_ctx``,
    ``_complete_node``, ``_fail_node``, ``_after_step_success``,
    ``_current_step_spec``, ``_enqueue_ready``, ``_pool_submitter``, and
    ``dispatch_ready_work``.
    """

    _scope_lease: ProcessWideScopeLease

    def _init_scope_lease(self) -> None:
        self._scope_lease = get_process_scope_lease()

    def release_held_scope_leases(self) -> None:
        """Release all process-wide claims held by this orchestrator (teardown)."""
        wake_callbacks = self._scope_lease.release_all_for_orchestrator(id(self))
        with self._condition:
            for node in self._nodes.values():
                if node.lease_step_kind is not None:
                    node.lease_step_kind = None
            for wake in wake_callbacks:
                self._observers.schedule_post_lock(wake)
        self._observers.drain_post_lock_callbacks()

    def _maybe_short_circuit_satisfied(
        self,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
    ) -> bool:
        """Complete ``node`` without running when durable satisfaction already holds.

        Returns True when the node was short-circuited (caller must not execute).
        """
        if not registration.persistence_policy.is_satisfied(self._cached_ctx, node.scope):
            return False
        self._metrics.satisfaction_short_circuits += 1
        # Dependents require a non-None result wire; content is analytic-owned and
        # readers that need durable artifacts re-load from persistence.
        if node.result_wire is None:
            node.result_wire = {}
        self._complete_node(node)
        return True

    def _acquire_scope_lease_or_park(
        self,
        node: ComputeNodeRun,
        step: ComputeStepSpec,
    ) -> bool:
        """Acquire the process-wide claim or park the node. True when acquired.

        Does not seal for execution -- the caller must
        :meth:`_seal_scope_lease_or_park` immediately before expensive work so a
        higher-priority peer can adopt during the post-dispatch job-wire window.
        """
        if node.lease_step_kind == step.step_kind:
            # Continuing the same step kind (e.g. tier_solve ladder) keeps the claim.
            self._metrics.lease_acquires += 1
            return True
        key = ScopeStepClaimKey(scope=node.scope, step_kind=step.step_kind)
        outcome = self._scope_lease.try_acquire(
            key,
            orchestrator_id=id(self),
            priority_band=node.priority_band,
            on_wake=lambda: self._wake_parked_for_lease(node.scope, step.step_kind),
        )
        if outcome == "parked":
            self._metrics.lease_parks += 1
            node.state = "parked"
            node.lease_step_kind = None
            return False
        if outcome == "adopted":
            self._metrics.lease_adopts += 1
        self._metrics.lease_acquires += 1
        node.lease_step_kind = step.step_kind
        return True

    def _seal_scope_lease_or_park(
        self,
        node: ComputeNodeRun,
        step: ComputeStepSpec,
    ) -> bool:
        """Seal the claim for expensive work, or recover after losing an adopt.

        True when sealed (caller must run). False when the node was parked or
        short-circuited after another binding adopted the claim.
        """
        key = ScopeStepClaimKey(scope=node.scope, step_kind=step.step_kind)
        result = self._scope_lease.seal_for_execution(key, orchestrator_id=id(self))
        if result.outcome == "sealed":
            return True
        with self._condition:
            node.lease_step_kind = None
            node.generation_at_submit = None
            registration = self._compute_registry.get(node.scope.analytic_id)
            if registration is not None and self._maybe_short_circuit_satisfied(
                node,
                registration,
            ):
                return False
            outcome = self._scope_lease.try_acquire(
                key,
                orchestrator_id=id(self),
                priority_band=node.priority_band,
                on_wake=lambda: self._wake_parked_for_lease(node.scope, step.step_kind),
            )
            if outcome == "parked":
                self._metrics.lease_parks += 1
                node.state = "parked"
                return False
            if outcome == "adopted":
                self._metrics.lease_adopts += 1
            self._metrics.lease_acquires += 1
            node.lease_step_kind = step.step_kind
            retry = self._scope_lease.seal_for_execution(key, orchestrator_id=id(self))
            if retry.outcome == "sealed":
                return True
            self._metrics.lease_parks += 1
            node.state = "parked"
            node.lease_step_kind = None
            return False

    def _run_inline_outside_lock(self, pending: _PendingInlineExecution) -> None:
        """Build wire, seal (adopt-safe), then run an inline step without the orch lock."""
        node = pending.node
        try:
            builder = pending.registration.build_step_job_wire[pending.step.step_kind]
            job_wire = builder(
                node.scope,
                dependency_outputs=pending.dependency_outputs,
                ctx=self._cached_ctx,
            )
        except BaseException as exc:
            with self._condition:
                self._metrics.inline_executions += 1
                self._observers.notify_step_complete(
                    node,
                    pending.step.step_kind,
                    surface="inline",
                    terminal_state="failed",
                )
                self._fail_node(node, exc)
            return
        # Seal after job-wire build so a higher-priority peer can adopt during
        # that window.
        if not self._seal_scope_lease_or_park(node, pending.step):
            return
        self._observers.notify_inline_start(node, pending.step.step_kind)
        try:
            result_wire = pending.registration.run_step[pending.step.step_kind](job_wire)
        except BaseException as exc:
            with self._condition:
                self._metrics.inline_executions += 1
                self._observers.notify_step_complete(
                    node,
                    pending.step.step_kind,
                    surface="inline",
                    terminal_state="failed",
                )
                self._fail_node(node, exc)
            return
        with self._condition:
            self._metrics.inline_executions += 1
            self._observers.notify_step_complete(
                node,
                pending.step.step_kind,
                surface="inline",
                terminal_state="success",
            )
            self._after_step_success(node, result_wire)

    def _flush_pending_pool_submissions(
        self,
        pending: tuple[_PendingPoolSubmission, ...],
    ) -> None:
        """Build job wires, seal, and submit pool work without the orchestrator lock."""
        if not pending:
            return
        if self._pool_submitter is None:
            raise RuntimeError("pool_submitter is not configured")
        for submission in pending:
            node = submission.node
            step = submission.step
            try:
                if step.backend in {"interpreter", "process"}:
                    builder = submission.registration.build_step_job_wire[step.step_kind]
                    job_wire = builder(
                        node.scope,
                        dependency_outputs=submission.dependency_outputs,
                        ctx=self._cached_ctx,
                    )
                    if not self._seal_scope_lease_or_park(node, step):
                        continue
                    run_step = submission.registration.run_step[step.step_kind]
                    self._pool_submitter(
                        node,
                        step,
                        job_wire=job_wire,
                        run_step=run_step,
                    )
                else:
                    if not self._seal_scope_lease_or_park(node, step):
                        continue
                    self._pool_submitter(node, step)
                self._metrics.pool_submissions += 1
            except BaseException as exc:
                with self._condition:
                    if node.state == "running":
                        self._observers.notify_step_complete(
                            node,
                            step.step_kind,
                            surface="pool",
                            terminal_state="failed",
                        )
                        self._fail_node(node, exc)

    def _wake_parked_for_lease(self, scope: ComputeScope, step_kind: str) -> None:
        """Resume a parked node after a peer binding released the scope lease."""
        should_dispatch = False
        with self._condition:
            node = self._nodes.get(scope)
            if node is None or node.state != "parked":
                return
            registration = self._compute_registry.get(node.scope.analytic_id)
            if registration is None:
                return
            try:
                current_step = self._current_step_spec(node, registration)
            except RuntimeError:
                return
            if current_step.step_kind != step_kind:
                return
            node.state = "ready"
            self._enqueue_ready(scope)
            self._observers.notify_ready(node)
            should_dispatch = True
        if should_dispatch:
            # Run dispatch on this (follower) orchestrator. The wake callback is
            # invoked from the leader's post-lock drain, so we must not only
            # schedule -- nothing else drains this orchestrator's callbacks.
            self.dispatch_ready_work()

    def _release_scope_lease(
        self,
        node: ComputeNodeRun,
        *,
        schedule_wakes: bool = True,
    ) -> tuple[Callable[[], None], ...]:
        """Release any process-wide claim held by ``node``.

        When ``schedule_wakes`` is True (default), waiter wake callbacks go onto the
        post-lock queue immediately -- correct for mid-profile step-kind handoff
        and teardown. Terminal complete/fail paths pass False and schedule wakes
        *after* process-scope terminal fan-out so stream listeners see the leader
        ``result_wire`` before a waiter short-circuits with ``{}``.
        """
        step_kind = node.lease_step_kind
        if step_kind is None:
            return ()
        key = ScopeStepClaimKey(scope=node.scope, step_kind=step_kind)
        node.lease_step_kind = None
        wake_callbacks = self._scope_lease.release(key, orchestrator_id=id(self))
        if schedule_wakes:
            for wake in wake_callbacks:
                self._observers.schedule_post_lock(wake)
        return wake_callbacks
