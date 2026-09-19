"""Step dispatch and post-lock execution helpers for ComputeOrchestrator.

Owns durable-satisfaction short-circuit, ready-queue dispatch into pending
inline/pool work, and seal-before-expensive-work execute paths that must run
only after the orchestrator lock is released. The DAG scheduler in
``orchestrator`` stays focused on readiness, singleflight, and terminal
lifecycle.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from api.compute.backend_runtime import effective_compute_backend
from api.compute.orchestrator_pending import PendingInlineExecution, PendingPoolSubmission
from api.compute.profile import ComputeBackend, ComputeStepSpec
from api.compute.registry import AnalyticComputeRegistration
from api.compute.wire import DependencyOutputs, RunStepFn, orchestration_plane_skip_result

if TYPE_CHECKING:
    from api.compute.orchestrator_state import ComputeNodeRun
    from api.compute.scope import ComputeScope


class OrchestratorStepExecutionMixin:
    """Short-circuit, dispatch, and post-lock step execution for the orchestrator.

    Expects the concrete orchestrator to provide ``_condition``, ``_nodes``,
    ``_ready_queue``, ``_metrics``, ``_observers``, ``_compute_registry``,
    ``_pool_submitter``, ``_ctx_for_node``, ``_complete_node``, ``_fail_node``,
    ``_after_step_success``, ``_deps_complete``, ``_enqueue_ready``,
    ``_ready_depth``, and ``_notify_ready_queue_changed``.
    """

    def _dispatch(
        self,
    ) -> tuple[tuple[PendingInlineExecution, ...], tuple[PendingPoolSubmission, ...]]:
        """Select and begin ready work under the orchestrator lock.

        Inline and pool steps are prepared here (state → running, dependency wires
        snapshotted) but job-wire construction and execution happen only after the
        caller releases the orchestrator lock.

        Before execution, durable satisfaction short-circuits the node so a node
        whose durable artifact already satisfies this step never re-runs it.
        """
        pending_inline: list[PendingInlineExecution] = []
        pending_pool: list[PendingPoolSubmission] = []
        initial_ready_depth = self._ready_depth()
        while self._ready_queue:
            scope, node = self._dequeue_dispatchable_ready_node()
            if scope is None or node is None:
                break

            registration = self._compute_registry[node.scope.analytic_id]
            step = self._current_step_spec(node, registration)
            if self._maybe_short_circuit_satisfied(node, registration):
                continue

            if step.backend == "inline":
                self._begin_step_execution(node)
                pending_inline.append(
                    PendingInlineExecution(
                        node=node,
                        registration=registration,
                        step=step,
                        dependency_outputs=self._snapshot_dependency_outputs(node),
                    )
                )
                continue

            if self._pool_submitter is None:
                # Cannot run yet; re-enqueue and stop this dispatch pass.
                self._enqueue_ready(scope)
                node.state = "ready"
                break
            self._begin_step_execution(node)
            pending_pool.append(
                PendingPoolSubmission(
                    node=node,
                    registration=registration,
                    step=step,
                    dependency_outputs=self._snapshot_dependency_outputs(node),
                )
            )
            break
        # Cover successful pops and ready→waiting_deps drops. ``_enqueue_ready`` /
        # ``_dequeue_ready`` notify on their own paths; this catches dispatch-only leaves.
        if self._ready_depth() != initial_ready_depth:
            self._notify_ready_queue_changed()
        return tuple(pending_inline), tuple(pending_pool)

    def _snapshot_dependency_outputs(self, node: ComputeNodeRun) -> DependencyOutputs:
        """Copy dependency result wires under the orchestrator lock."""
        dependency_outputs = DependencyOutputs()
        for dependency_scope in node.dependency_scopes:
            dependency_node = self._nodes[dependency_scope]
            if dependency_node.result_wire is None:
                raise RuntimeError(
                    f"dependency {dependency_scope!r} is complete without a result wire"
                )
            dependency_outputs.put(dependency_scope, dependency_node.result_wire)
        return dependency_outputs

    def _execute_pending_inlines(
        self,
        pending: tuple[PendingInlineExecution, ...],
    ) -> None:
        """Build and run accepted inline steps without holding the orchestrator lock."""
        for item in pending:
            self._run_inline_outside_lock(item)

    def _dequeue_dispatchable_ready_node(
        self,
    ) -> tuple[ComputeScope | None, ComputeNodeRun | None]:
        queue_len = len(self._ready_queue)
        if queue_len == 0:
            return None, None
        for _ in range(queue_len):
            scope = self._ready_queue.popleft()
            node = self._nodes[scope]
            if node.state != "ready":
                continue
            if not self._deps_complete(node):
                node.state = "waiting_deps"
                continue
            # Gates first (side-effect free), then commit hooks (may consume slots).
            # Evaluating commits inside ``all(gate)`` burned single-step slots when a
            # later gate (e.g. scores global-pause) rejected the same node.
            if not all(gate(node) for gate in self._observers.dispatch_gates):
                self._ready_queue.append(scope)
                continue
            if not all(hook(node) for hook in self._observers.dispatch_commit_hooks):
                self._ready_queue.append(scope)
                continue
            return scope, node
        return None, None

    def _effective_pool_backend(
        self,
        step: ComputeStepSpec,
        registration: AnalyticComputeRegistration,
    ) -> ComputeBackend:
        """Return the backend the worker pool should run for this step.

        Registration may remap occupancy (declared thread -> process). Frozen
        runtime then remaps interpreter -> thread. Sampled at flush, not import.
        """
        declared = step.backend
        resolver = registration.resolve_step_backend
        if resolver is not None:
            declared = resolver(step.step_kind, declared)
        return effective_compute_backend(declared)

    def _pool_run_step(
        self,
        registration: AnalyticComputeRegistration,
        step_kind: str,
        effective_backend: ComputeBackend,
    ) -> RunStepFn:
        if effective_backend in {"interpreter", "process"}:
            remote = registration.remote_run_step.get(step_kind)
            if remote is not None:
                return remote
        return registration.run_step[step_kind]

    def map_remote_pool_result(
        self,
        scope: ComputeScope,
        result_wire: object,
        *,
        step_kind: str | None = None,
    ) -> object:
        """Map a pickle-safe remote leaf payload on the parent before coerce.

        Runs on the pool done-callback thread, not under the orchestrator lock.
        Scores soft-defer talks to the inference scheduler here -- the same
        order as in-process ``run_scores_tier_solve``.
        """
        if step_kind is None:
            return result_wire
        registration = self._compute_registry.get(scope.analytic_id)
        if registration is None:
            return result_wire
        mapper = registration.map_remote_step_result.get(step_kind)
        if mapper is None:
            return result_wire
        return mapper(scope, result_wire)

    def _current_step_spec(
        self,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
    ) -> ComputeStepSpec:
        steps = registration.compute_profile.steps
        if node.profile_step_index >= len(steps):
            raise RuntimeError(
                f"compute node {node.scope!r} has no step at profile index "
                f"{node.profile_step_index}"
            )
        return steps[node.profile_step_index]

    def _begin_step_execution(self, node: ComputeNodeRun) -> None:
        registration = self._compute_registry[node.scope.analytic_id]
        node.state = "running"
        # Adopt window reopens while the job wire for this step is (re)built.
        node.execution_sealed = False
        ctx = self._ctx_for_node(node)
        node.generation_at_submit = registration.persistence_policy.invalidation_generation(
            ctx,
            node.scope,
        )

    def _maybe_short_circuit_satisfied(
        self,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
    ) -> bool:
        """Complete ``node`` without running when durable satisfaction already holds.

        Returns True when the node was short-circuited (caller must not execute).
        """
        ctx = self._ctx_for_node(node)
        if not registration.persistence_policy.is_satisfied(ctx, node.scope):
            return False
        self._metrics.satisfaction_short_circuits += 1
        # Dependents and stream listeners need a non-None wire. Prefer the analytic's
        # satisfied wire (e.g. fleet ledger); otherwise ``{}`` and readers fall back
        # to persistence.
        if node.result_wire is None:
            hydrated = registration.persistence_policy.satisfied_result_wire(
                ctx,
                node.scope,
            )
            node.result_wire = {} if hydrated is None else hydrated
        self._complete_node(node)
        return True

    def _run_inline_outside_lock(self, pending: PendingInlineExecution) -> None:
        """Build wire, seal for execution, then run an inline step without the orch lock."""
        node = pending.node
        ctx = self._ctx_for_node(node)
        try:
            builder = pending.registration.build_step_job_wire[pending.step.step_kind]
            job_wire = builder(
                node.scope,
                dependency_outputs=pending.dependency_outputs,
                ctx=ctx,
                node_result_wire=node.result_wire,
            )
        except BaseException as exc:
            with self._condition:
                self._metrics.inline_executions += 1
                self._observers.notify_step_complete(
                    node,
                    pending.step.step_kind,
                    step_index=node.step_index,
                    surface="inline",
                    terminal_state="failed",
                )
                self._fail_node(node, exc)
            return
        # Seal after job-wire build: a higher-priority peer can adopt during that
        # window (see ``_maybe_adopt_priority``), but not once the run itself starts.
        with self._condition:
            if node.state != "running":
                return
            node.execution_sealed = True
        self._observers.notify_inline_start(node, pending.step.step_kind)
        try:
            result_wire = pending.registration.run_step[pending.step.step_kind](job_wire)
        except BaseException as exc:
            with self._condition:
                self._metrics.inline_executions += 1
                self._observers.notify_step_complete(
                    node,
                    pending.step.step_kind,
                    step_index=node.step_index,
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
                step_index=node.step_index,
                surface="inline",
                terminal_state="success",
            )
            self._after_step_success(node, result_wire)

    def _flush_pending_pool_submissions(
        self,
        pending: tuple[PendingPoolSubmission, ...],
    ) -> None:
        """Build job wires, seal, and submit pool work without the orchestrator lock."""
        if not pending:
            return
        if self._pool_submitter is None:
            raise RuntimeError("pool_submitter is not configured")
        for submission in pending:
            node = submission.node
            step = submission.step
            ctx = self._ctx_for_node(node)
            try:
                effective_backend = self._effective_pool_backend(step, submission.registration)
                submit_step = (
                    step
                    if step.backend == effective_backend
                    else replace(step, backend=effective_backend)
                )
                if effective_backend in {"interpreter", "process"}:
                    builder = submission.registration.build_step_job_wire[step.step_kind]
                    job_wire = builder(
                        node.scope,
                        dependency_outputs=submission.dependency_outputs,
                        ctx=ctx,
                        node_result_wire=node.result_wire,
                    )
                    skip_result = orchestration_plane_skip_result(job_wire)
                    with self._condition:
                        if node.state != "running":
                            continue
                        node.execution_sealed = True
                        if skip_result is not None:
                            self._observers.notify_step_complete(
                                node,
                                step.step_kind,
                                step_index=node.step_index,
                                surface="inline",
                                terminal_state="success",
                            )
                            self._after_step_success(node, skip_result)
                            continue
                    run_step = self._pool_run_step(
                        submission.registration,
                        step.step_kind,
                        effective_backend,
                    )
                    self._pool_submitter(
                        node,
                        submit_step,
                        job_wire=job_wire,
                        run_step=run_step,
                    )
                else:
                    with self._condition:
                        if node.state != "running":
                            continue
                        node.execution_sealed = True
                    self._pool_submitter(node, submit_step)
                self._metrics.pool_submissions += 1
            except BaseException as exc:
                with self._condition:
                    if node.state == "running":
                        self._observers.notify_step_complete(
                            node,
                            step.step_kind,
                            step_index=node.step_index,
                            surface="pool",
                            terminal_state="failed",
                        )
                        self._fail_node(node, exc)
