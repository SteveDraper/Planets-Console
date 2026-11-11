"""Step dispatch and post-lock execution helpers for ComputeOrchestrator.

Owns durable-satisfaction short-circuit, the band derivation each dispatch
pass runs and publishes for the worker pool, band-ordered ready-queue dispatch
into pending inline/pool work, and the execute paths that must run only after
the orchestrator lock is released. The DAG scheduler in ``orchestrator`` stays
focused on readiness, singleflight, and terminal lifecycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.compute.backend_runtime import effective_compute_backend
from api.compute.orchestrator_pending import PendingInlineExecution, PendingPoolSubmission
from api.compute.pools import PoolStepWork, RemoteStepWork, ThreadStepWork
from api.compute.priority_band import (
    PRIORITY_BAND_RANK,
    derive_priority_bands,
    snapshot_watched_keys,
)
from api.compute.profile import ComputeStepSpec
from api.compute.registry import AnalyticComputeRegistration
from api.compute.wire import BuildStepJobWireKwargs, DependencyOutputs

if TYPE_CHECKING:
    from api.compute.orchestrator_state import ComputeNodeRun
    from api.compute.scope import ComputeScope


class OrchestratorStepExecutionMixin:
    """Short-circuit, dispatch, and post-lock step execution for the orchestrator.

    Expects the concrete orchestrator to provide ``_condition``, ``_nodes``,
    ``_published_bands``, ``_ready_queue``, ``_metrics``, ``_observers``,
    ``_compute_registry``, ``_pool_submitter``, ``_ctx_for_node``,
    ``_complete_node``, ``_fail_node``,
    ``_after_step_success``, ``_deps_complete``, ``_enqueue_ready``,
    ``_ready_depth``, and ``_notify_ready_queue_changed``.
    """

    def _dispatch(
        self,
    ) -> tuple[tuple[PendingInlineExecution, ...], tuple[PendingPoolSubmission, ...]]:
        """Select and begin ready work under the orchestrator lock.

        Inline and pool steps are prepared here (state → running, job-wire builder
        kwargs snapshotted) but job-wire construction and execution happen only after the
        caller releases the orchestrator lock.

        Before execution, durable satisfaction short-circuits the node so a node
        whose durable artifact already satisfies this step never re-runs it.

        The pass starts by deriving every non-terminal node's band, which
        orders the ready pick and is published for the worker pool.
        """
        self._derive_and_publish_bands()
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
                        job_wire_kwargs=self._snapshot_job_wire_kwargs(node),
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
                    job_wire_kwargs=self._snapshot_job_wire_kwargs(node),
                )
            )
            break
        # Cover successful pops and ready→waiting_deps drops. ``_enqueue_ready`` /
        # ``_dequeue_ready`` notify on their own paths; this catches dispatch-only leaves.
        if self._ready_depth() != initial_ready_depth:
            self._notify_ready_queue_changed()
        return tuple(pending_inline), tuple(pending_pool)

    def _derive_and_publish_bands(self) -> None:
        """Derive every non-terminal node's band, write it, and publish the map.

        Caller holds the orchestrator lock. Each watch is read once, from
        lock-free snapshots. Running nodes are written too: a pool step is not
        picked until a worker takes it, and a picked step's band lives on its
        execution records. Readers of the published map take no lock, so it is
        swapped in one assignment.
        """
        bands = derive_priority_bands(
            self._nodes,
            snapshot_watched_keys(self._compute_registry),
            self._compute_registry,
        )
        for scope, band in bands.items():
            self._nodes[scope].priority_band = band
        self._published_bands = bands

    def _snapshot_job_wire_kwargs(self, node: ComputeNodeRun) -> BuildStepJobWireKwargs:
        """Snapshot the job-wire builder kwargs for ``node``'s current step.

        Caller holds the orchestrator lock. Taken once per step, at dispatch:
        inline, interpreter, process and thread builders all run from this
        snapshot after the lock is released.
        """
        dependency_outputs = DependencyOutputs()
        for dependency_scope in node.dependency_scopes:
            dependency_node = self._nodes[dependency_scope]
            if dependency_node.result_wire is None:
                raise RuntimeError(
                    f"dependency {dependency_scope!r} is complete without a result wire"
                )
            dependency_outputs.put(dependency_scope, dependency_node.result_wire)
        return BuildStepJobWireKwargs(
            dependency_outputs=dependency_outputs,
            ctx=self._ctx_for_node(node),
            node_result_wire=node.result_wire,
            submission_open=node.submission_open,
            execution_generation=node.execution_generation,
        )

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
        """Remove and return the first dispatchable ready node by band, then FIFO.

        Entries no longer ``ready`` leave the queue, and a ready node whose
        dependencies are incomplete drops to ``waiting_deps``. A node a gate or
        commit hook rejects keeps its queue position.
        """
        by_band = sorted(
            self._ready_queue,
            key=lambda scope: PRIORITY_BAND_RANK[self._nodes[scope].priority_band],
        )
        for scope in by_band:
            node = self._nodes[scope]
            if node.state != "ready":
                self._ready_queue.remove(scope)
                continue
            if not self._deps_complete(node):
                self._ready_queue.remove(scope)
                node.state = "waiting_deps"
                continue
            # Gates first (side-effect free), then commit hooks (may consume slots).
            # Evaluating commits inside ``all(gate)`` burned single-step slots when a
            # later gate (e.g. scores global-pause) rejected the same node.
            if not all(gate(node) for gate in self._observers.dispatch_gates):
                continue
            if not all(hook(node) for hook in self._observers.dispatch_commit_hooks):
                continue
            self._ready_queue.remove(scope)
            return scope, node
        return None, None

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
        """Build the wire, then run an inline step without the orchestrator lock."""
        node = pending.node
        try:
            builder = pending.registration.build_step_job_wire[pending.step.step_kind]
            job_wire = builder(node.scope, **pending.job_wire_kwargs)
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
            if node.state != "running":
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
        """Turn each submission's dispatch-time builder inputs into pool work and submit it.

        Interpreter and process steps get their job wire built here. A thread
        step, including a declared ``interpreter`` step remapped to ``thread``,
        carries the builder inputs to the pool worker, which builds the wire there.
        Either way the wire is built from the one snapshot taken at dispatch.
        """
        if not pending:
            return
        if self._pool_submitter is None:
            raise RuntimeError("pool_submitter is not configured")
        for submission in pending:
            node = submission.node
            step = submission.step
            try:
                build_job_wire = submission.registration.build_step_job_wire[step.step_kind]
                run_step = submission.registration.run_step[step.step_kind]
                work: PoolStepWork
                if effective_compute_backend(step.backend) == "thread":
                    work = ThreadStepWork(
                        build_job_wire=build_job_wire,
                        job_wire_kwargs=submission.job_wire_kwargs,
                        run_step=run_step,
                    )
                else:
                    work = RemoteStepWork(
                        job_wire=build_job_wire(node.scope, **submission.job_wire_kwargs),
                        run_step=run_step,
                    )
                with self._condition:
                    if node.state != "running":
                        continue
                self._pool_submitter(node, step, work=work)
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
