"""Step dispatch and post-lock execution helpers for ComputeOrchestrator.

Owns durable-satisfaction short-circuit, the band derivation each dispatch
pass runs and publishes for the worker pool, band-ordered ready-queue dispatch
into pending inline/pool work, and the execute paths that must run only after
the orchestrator lock is released. The DAG scheduler in ``orchestrator`` stays
focused on readiness, singleflight, and terminal lifecycle.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING

from api.compute.backend_runtime import effective_pool_backend
from api.compute.orchestrator_pending import (
    DispatchedWork,
    PendingInlineExecution,
    PendingPoolSubmission,
    PendingStep,
)
from api.compute.orchestrator_state import PublishedExecution
from api.compute.pools import PoolStepWork
from api.compute.priority_band import (
    PRIORITY_BAND_RANK,
    derive_priority_bands,
    snapshot_watched_keys,
)
from api.compute.profile import ComputeStepSpec
from api.compute.registry import AnalyticComputeRegistration
from api.compute.running_step import StepExit
from api.compute.wire import BuildStepJobWireKwargs, DependencyOutputs

if TYPE_CHECKING:
    from api.compute.orchestrator_observers import StepSurface
    from api.compute.orchestrator_state import ComputeNodeRun
    from api.compute.scope import ComputeScope

logger = logging.getLogger(__name__)


class OrchestratorStepExecutionMixin:
    """Short-circuit, dispatch, and post-lock step execution for the orchestrator.

    Expects the concrete orchestrator to provide ``_condition``, ``_nodes``,
    ``_published_executions``, ``_ready_queue``, ``_metrics``, ``_observers``,
    ``_compute_registry``, ``_pool_submitter``, ``_ctx_for_node``,
    ``_complete_node``, ``_fail_node``, ``_refuse_step_exit``,
    ``_finish_step``, ``_running_execution``, ``_running_execution_or_record_ignored``,
    ``_deps_complete``, ``_refresh_all_readiness``, ``_refresh_node_readiness``,
    ``_ready_depth``, and ``_notify_ready_queue_changed``.
    """

    def _run_dispatch_pass(self, *, refresh_all: bool = False) -> bool:
        """Run one dispatch pass and hand off everything it committed.

        The pass runs under the orchestrator lock; the hand-off runs after the
        lock is released, even when the pass raised partway, so every node the
        pass marked ``running`` gets its inline run or pool item. With
        ``refresh_all``, every node's readiness is refreshed first in the
        same hold, so the pass dispatches exactly what that refresh made
        ready. Returns whether any node is running when the pass ends, read
        in that hold. ``run_until_idle`` is the one caller that uses either: it
        checks for pending work in an earlier hold of its own, and anything
        that changes before the pass's hold is simply what the pass refreshes
        and dispatches.
        """
        work = DispatchedWork()
        try:
            with self._condition:
                if refresh_all:
                    self._refresh_all_readiness()
                self._dispatch(work)
                return any(node.state == "running" for node in self._nodes.values())
        finally:
            self._hand_off(work)

    def _dispatch(self, work: DispatchedWork) -> None:
        """Select and commit every dispatchable ready node into ``work``, under the lock.

        The pass starts by deriving every non-terminal node's band, which
        orders the sweep and is published for the worker pool. It then walks
        the ready queue once, in band order (:meth:`_dispatchable_ready_nodes`),
        and commits every node that its gates and commit hooks admit, inline
        and pool alike. So ready work is left in the queue only while a gate
        or commit hook holds it, or when no ``pool_submitter`` is configured.

        For each picked node, everything that can raise happens first, in this
        order: step spec, durable-satisfaction short-circuit, the START gate,
        the invalidation-generation read and the job-wire snapshot. Only then
        is the node marked ``running`` and its record appended, which cannot
        raise. So a node is ``running`` only once its record is in ``work``.
        A raise while preparing one node fails that node and the pass goes on.
        A pool step with no ``pool_submitter`` configured keeps its queue
        position and ends the pass. A dispatch gate or commit hook that raises ends the pass with
        that error; records already committed stay in ``work``.

        Job-wire construction and execution happen only after the caller
        releases the lock.
        """
        self._derive_and_publish_bands()
        initial_ready_depth = self._ready_depth()
        try:
            for node in self._dispatchable_ready_nodes():
                try:
                    registration = self._compute_registry[node.scope.analytic_id]
                    step = self._current_step_spec(node, registration)
                    if self._maybe_short_circuit_satisfied(node, registration):
                        continue
                except Exception as exc:
                    self._fail_unstarted_node(node, exc)
                    continue
                is_pool_step = step.backend != "inline"
                if is_pool_step and self._pool_submitter is None:
                    # Cannot run yet: it keeps its queue position, and the pass ends.
                    break
                try:
                    if self._refuse_step_exit(node, StepExit.START):
                        continue
                    generation_at_submit = registration.persistence_policy.invalidation_generation(
                        self._ctx_for_node(node),
                        node.scope,
                    )
                    job_wire_kwargs = self._snapshot_job_wire_kwargs(node)
                except Exception as exc:
                    self._fail_unstarted_node(node, exc)
                    continue
                node.state = "running"
                node.generation_at_submit = generation_at_submit
                if is_pool_step:
                    work.pool.append(
                        PendingPoolSubmission(
                            node, registration, step, job_wire_kwargs, node.execution_generation
                        )
                    )
                else:
                    work.inline.append(
                        PendingInlineExecution(
                            node, registration, step, job_wire_kwargs, node.execution_generation
                        )
                    )
        finally:
            # One rebuild instead of a removal per commit: every node the pass
            # committed, settled or refused is no longer ``ready``.
            self._ready_queue = deque(
                scope for scope in self._ready_queue if self._nodes[scope].state == "ready"
            )
            # ``_enqueue_ready`` / ``_dequeue_ready`` notify on their own paths; this
            # covers committed nodes and entries the sweep found no longer ready.
            if self._ready_depth() != initial_ready_depth:
                self._notify_ready_queue_changed()

    def _fail_unstarted_node(self, node: ComputeNodeRun, error: Exception) -> None:
        """Fail a picked node whose step could not be prepared. Caller holds the lock.

        The node was never marked ``running``. A node the preparation already
        ended (for example the START gate) is left as it is.
        """
        logger.exception("Preparing compute node %r for dispatch failed", node.scope)
        if not node.is_terminal:
            self._fail_node(node, error)

    def _derive_and_publish_bands(self) -> None:
        """Derive every non-terminal node's band, write it, and publish the map.

        Caller holds the orchestrator lock. Each watch is read once, from
        lock-free snapshots. Running nodes are written too: a pool step is not
        picked until a worker takes it, and a picked step's band lives on its
        execution records. Each entry also carries the node's execution
        generation, so the pool can tell an item of an ended execution without
        the orchestrator lock. Readers of the published map take no lock, so it
        is swapped in one assignment. This is the only place the map is
        published.
        """
        bands = derive_priority_bands(
            self._nodes,
            snapshot_watched_keys(self._compute_registry),
            self._compute_registry,
        )
        published: dict[ComputeScope, PublishedExecution] = {}
        for scope, band in bands.items():
            node = self._nodes[scope]
            node.priority_band = band
            published[scope] = PublishedExecution(
                band=band,
                execution_generation=node.execution_generation,
            )
        self._published_executions = MappingProxyType(published)

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
            is_execution_live=partial(node.is_live_execution, node.execution_generation),
        )

    def _hand_off(self, work: DispatchedWork) -> None:
        """Submit committed pool steps, run committed inline steps, then drain callbacks.

        When this thread is already draining, the drain returns at once and the
        active drain runs the callbacks the inline steps queued, including the
        next dispatch pass of an inline chain, so a chain never nests hand-offs.

        Runs after the orchestrator lock is released. Pool steps go first:
        submitting one only enqueues it, so pool workers start before an
        inline step occupies this thread. A failure of one record fails only
        that record's own attempt (:meth:`_fail_running_step`) and the rest
        still run. Each stage also runs whatever an earlier stage raised, so
        a raise that escapes one stage never strands the next stage's
        records or the post-lock callbacks; it propagates once all have run.
        When more than one stage raises, only the last raise propagates, with
        the earlier one as its ``__context__``.
        """
        try:
            self._flush_pending_pool_submissions(work.pool)
        finally:
            try:
                self._run_inline_records(work.inline)
            finally:
                self._observers.drain_post_lock_callbacks()

    def _run_inline_records(self, records: list[PendingInlineExecution]) -> None:
        """Run each committed inline step outside the lock, isolating each failure."""
        for item in records:
            try:
                self._run_inline_outside_lock(item)
            except BaseException as exc:
                logger.exception("Handing off inline step for %r failed", item.node.scope)
                self._fail_running_step(item, "inline", exc)

    def _fail_running_step(
        self,
        item: PendingStep,
        surface: StepSurface,
        error: BaseException,
    ) -> None:
        """Fail ``item``'s node when this attempt failed before it was handed on.

        Takes the orchestrator lock. Acts only while the attempt has not been
        handed on (``item.is_handed_on``) and the node is still running
        the execution the attempt was dispatched for. Records the step as
        failed, then fails the node.
        """
        with self._condition:
            if item.is_handed_on:
                return
            node = self._running_execution(item.node.scope, item.execution_generation)
            if node is None:
                return
            self._observers.notify_step_complete(
                node,
                item.step.step_kind,
                step_index=node.step_index,
                surface=surface,
                terminal_state="failed",
            )
            self._fail_node(node, error)

    def _dispatchable_ready_nodes(self) -> Iterator[ComputeNodeRun]:
        """Yield each ready node a dispatch pass may commit, once, by band then FIFO.

        Caller holds the lock and has derived this pass's bands. The sweep
        sorts one snapshot of the ready queue: bands are fixed for the pass,
        and nothing the pass does re-enters the queue, so a later entry needs
        no re-sort. Each entry is re-checked when it is reached, because
        preparing an earlier node can end this one. An entry no longer
        ``ready`` is skipped; the caller drops it from the queue at the end. A ready
        node whose dependencies are incomplete has its readiness refreshed:
        it fails on a dependency failure that cascades, else drops to
        ``waiting_deps``. No known path queues such a node (every return to
        dispatch resolves readiness), so this backs up that invariant.

        Gates run first (side-effect free), then commit hooks (which may
        consume a slot), each once per node per pass. A node either one
        rejects keeps its queue position. Gates and commit hooks must never
        become more permissive because of a commit earlier in the same pass,
        which is what lets one sweep stand for re-checking the whole queue
        after every commit. Evaluating commit hooks inside ``all(gate)``
        would burn single-step slots when a later gate (e.g. scores
        global-pause) rejects the same node.
        """
        by_band = sorted(
            self._ready_queue,
            key=lambda scope: PRIORITY_BAND_RANK[self._nodes[scope].priority_band],
        )
        for scope in by_band:
            node = self._nodes[scope]
            if node.state != "ready":
                continue
            if not self._deps_complete(node):
                self._refresh_node_readiness(node)
                continue
            if not all(gate(node) for gate in self._observers.dispatch_gates):
                continue
            if not all(hook(node) for hook in self._observers.dispatch_commit_hooks):
                continue
            yield node

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
        """Build the wire, then run an inline step without the orchestrator lock.

        The execution can end while its wire builds or its step runs, for
        example aborted by a settle. Each finish applies only while the
        execution is still running; otherwise it is recorded as
        ``inline_finish_ignored`` and the ended node is left as it is.
        """
        node = pending.node
        try:
            builder = pending.registration.build_step_job_wire[pending.step.step_kind]
            job_wire = builder(node.scope, **pending.job_wire_kwargs)
        except BaseException as exc:
            self._finish_inline_step(pending, failure=exc)
            return
        with self._condition:
            if node.state != "running" or self._refuse_step_exit(node, StepExit.START):
                return
        self._observers.notify_inline_start(node, pending.step.step_kind)
        try:
            result_wire = pending.registration.run_step[pending.step.step_kind](job_wire)
        except BaseException as exc:
            self._finish_inline_step(pending, failure=exc)
            return
        self._finish_inline_step(pending, result_wire=result_wire)

    def _finish_inline_step(
        self,
        pending: PendingInlineExecution,
        *,
        result_wire: object | None = None,
        failure: BaseException | None = None,
    ) -> None:
        """Apply an inline step's result or failure to its execution, if still running.

        Marks the attempt handed on before applying its finish. A raise while
        applying fails the execution if it is still running, in the same hold.
        """
        node = pending.node
        with self._condition:
            self._metrics.inline_executions += 1
            running = self._running_execution_or_record_ignored(
                "inline_finish_ignored",
                node.scope,
                pending.execution_generation,
                step_kind=pending.step.step_kind,
                step_index=node.step_index,
                had_error=failure is not None,
            )
            if running is None:
                return
            pending.is_handed_on = True
            try:
                self._finish_step(
                    running,
                    pending.step.step_kind,
                    step_index=running.step_index,
                    surface="inline",
                    result_wire=result_wire,
                    failure=failure,
                )
            except Exception as exc:
                # Same lock hold: if the finish left this execution running,
                # nothing else can have re-dispatched it, so failing it here
                # cannot touch a retry.
                logger.exception("Applying the inline finish of %r failed", node.scope)
                if running.is_running_execution(pending.execution_generation):
                    self._fail_node(running, exc)

    def _flush_pending_pool_submissions(
        self,
        pending: list[PendingPoolSubmission],
    ) -> None:
        """Turn each submission's dispatch-time builder inputs into pool work and submit it.

        No job wire is built here: the pool worker builds it from the one
        snapshot taken at dispatch, whatever the step's backend, so the thread
        that runs a dispatch pass (often a request thread) builds none. The
        backend the step runs on is resolved here, once
        (:func:`effective_pool_backend`).

        Never raises. A submission whose work or submit raises fails its own
        attempt (:meth:`_fail_running_step`); the rest are still submitted.
        A submitter that returns has accepted the item, which then belongs to
        the pool, so the submission is marked handed on in the next hold.
        Dispatch commits pool work only while a ``pool_submitter`` is
        configured; otherwise it leaves the pool step in the ready queue at
        its position and ends the pass.
        """
        for submission in pending:
            node = submission.node
            step = submission.step
            try:
                work = PoolStepWork(
                    backend=effective_pool_backend(step.backend),
                    build_job_wire=submission.registration.build_step_job_wire[step.step_kind],
                    job_wire_kwargs=submission.job_wire_kwargs,
                    run_step=submission.registration.run_step[step.step_kind],
                )
                with self._condition:
                    if node.state != "running":
                        continue
                self._pool_submitter(node, step, work=work)
                with self._condition:
                    submission.is_handed_on = True
                    self._metrics.pool_submissions += 1
            except BaseException as exc:
                logger.exception("Submitting pool step for %r failed", node.scope)
                self._fail_running_step(submission, "pool", exc)
