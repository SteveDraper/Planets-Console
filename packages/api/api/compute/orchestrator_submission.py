"""Submission, singleflight attachment, and DAG planning for ComputeOrchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.compute.dag import PlannedComputeNode, plan_compute_dag
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.orchestrator_state import ComputeHandle, ComputeNodeRun
from api.compute.orchestrator_step_execution import (
    _PendingInlineExecution,
    _PendingPoolSubmission,
)
from api.compute.pools import PRIORITY_BAND_RANK, ComputePriorityBand
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope, compute_scope_to_export_scope

if TYPE_CHECKING:
    from api.compute.orchestrator import (
        ComputeOrchestrator,
        ComputeRequest,
    )


class OrchestratorSubmissionMixin:
    """Submit, wake, attach, and plan compute work under the orchestrator lock."""

    def submit(self: ComputeOrchestrator, request: ComputeRequest) -> ComputeHandle:
        """Submit or attach to in-flight work for one compute scope."""
        with self._condition:
            submission = self._submit_locked(request, wake_if_parked_only=False)
        return self._finish_submission(submission)

    def wake_if_parked(
        self: ComputeOrchestrator,
        request: ComputeRequest,
    ) -> ComputeHandle | None:
        """Atomically wake a soft-parked scope, or no-op for every other state."""
        if not request.force_fresh:
            raise ValueError("wake_if_parked requires force_fresh=True")
        with self._condition:
            submission = self._submit_locked(request, wake_if_parked_only=True)
        return None if submission is None else self._finish_submission(submission)

    def _submit_locked(
        self: ComputeOrchestrator,
        request: ComputeRequest,
        *,
        wake_if_parked_only: bool,
    ) -> (
        tuple[
            ComputeHandle,
            tuple[_PendingInlineExecution, ...],
            tuple[_PendingPoolSubmission, ...],
        ]
        | None
    ):
        """Apply one submission under the orchestrator lock."""
        scope = request.scope
        existing = self._nodes.get(scope)
        if wake_if_parked_only and (existing is None or existing.state != "parked"):
            return None

        pending_inline: tuple[_PendingInlineExecution, ...] = ()
        pending_pool: tuple[_PendingPoolSubmission, ...] = ()
        if existing is not None:
            if not (request.force_fresh and existing.state in {"complete", "failed"}):
                if request.force_fresh:
                    self._emit_force_fresh_lifecycle(
                        kind="force_fresh_attach",
                        node=existing,
                        request=request,
                    )
                    self._maybe_wake_parked_node(existing)
                handle = self._attach_to_existing(existing, request)
                pending_inline, pending_pool = self._dispatch()
            else:
                self._emit_force_fresh_lifecycle(
                    kind="force_fresh_replace",
                    node=existing,
                    request=request,
                )
                self._replace_terminal_node(existing)
                handle, pending_inline, pending_pool = self._plan_submission_locked(request)
        else:
            handle, pending_inline, pending_pool = self._plan_submission_locked(request)
        return handle, pending_inline, pending_pool

    def _plan_submission_locked(
        self: ComputeOrchestrator,
        request: ComputeRequest,
    ) -> tuple[
        ComputeHandle,
        tuple[_PendingInlineExecution, ...],
        tuple[_PendingPoolSubmission, ...],
    ]:
        """Plan a fresh scope and select its first dispatchable work."""
        scope = request.scope
        bundle = self._require_bundle(request)
        self._plan_and_register(
            scope,
            bundle=bundle,
            priority_band=request.priority_band,
            entry_step_kind=request.step_kind,
        )
        for node in self._nodes.values():
            self._refresh_node_readiness(node)
        return ComputeHandle(scope=scope, _node=self._nodes[scope]), *self._dispatch()

    def _finish_submission(
        self: ComputeOrchestrator,
        submission: tuple[
            ComputeHandle,
            tuple[_PendingInlineExecution, ...],
            tuple[_PendingPoolSubmission, ...],
        ],
    ) -> ComputeHandle:
        """Run work selected by a submission after releasing the lock."""
        handle, pending_inline, pending_pool = submission
        self._execute_pending_inlines(pending_inline)
        self._flush_pending_pool_submissions(pending_pool)
        self._observers.drain_post_lock_callbacks()
        return handle

    def _require_bundle(
        self: ComputeOrchestrator,
        request: ComputeRequest,
    ) -> OrchestrationBundle:
        bundle = request.resolved_bundle()
        if bundle is None:
            raise ValueError("ComputeRequest requires bundle= or ctx= for new work")
        return bundle

    def _attach_to_existing(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        request: ComputeRequest,
    ) -> ComputeHandle:
        if node.state in {"complete", "failed"}:
            return ComputeHandle(scope=node.scope, _node=node)
        handle = ComputeHandle(scope=node.scope, _node=node, is_waiter=True)
        node.waiters.append(handle)
        self._maybe_adopt_priority(node, request.priority_band)
        return handle

    def _maybe_adopt_priority(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        priority_band: ComputePriorityBand,
    ) -> None:
        """Upgrade a node's priority from a higher-priority attachment."""
        if node.execution_sealed:
            return
        if node.state not in {"waiting_deps", "parked", "ready", "running"}:
            return
        if PRIORITY_BAND_RANK[priority_band] >= PRIORITY_BAND_RANK[node.priority_band]:
            return
        node.priority_band = priority_band

    def _replace_terminal_node(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        if node.state not in {"complete", "failed"}:
            raise RuntimeError(f"cannot replace non-terminal node in state {node.state!r}")
        self._dequeue_ready(node.scope)
        node.waiters.clear()
        self._nodes.pop(node.scope, None)

    def _plan_and_register(
        self: ComputeOrchestrator,
        root_scope: ComputeScope,
        *,
        bundle: OrchestrationBundle,
        priority_band: ComputePriorityBand,
        entry_step_kind: str | None = None,
    ) -> None:
        export_scope = compute_scope_to_export_scope(root_scope)
        ctx = self._ctx_for_bundle(bundle)
        planned_nodes = plan_compute_dag(
            ctx,
            root_scope.analytic_id,
            export_scope,
            compute_registry=self._compute_registry,
            force_root=entry_step_kind is not None,
        )
        self._turn_cache.prefetch_planned_nodes(
            planned_nodes,
            load_turn=bundle.query_context.load_turn,
            game_id=bundle.game_id,
            perspective=bundle.perspective,
        )
        for planned in planned_nodes:
            self._register_planned_node(
                planned,
                bundle=bundle,
                priority_band=priority_band,
                entry_step_kind=entry_step_kind if planned.scope == root_scope else None,
            )
        if root_scope not in self._nodes:
            self._nodes[root_scope] = ComputeNodeRun(
                scope=root_scope,
                dependency_scopes=(),
                state="complete",
                priority_band=priority_band,
                execution_generation=self._allocate_execution_generation(),
                bundle=bundle,
            )

    def _register_planned_node(
        self: ComputeOrchestrator,
        planned: PlannedComputeNode,
        *,
        bundle: OrchestrationBundle,
        priority_band: ComputePriorityBand,
        entry_step_kind: str | None = None,
    ) -> None:
        if planned.scope in self._nodes:
            return
        registration = self._compute_registry[planned.scope.analytic_id]
        profile_step_index = self._resolve_profile_step_index(
            registration,
            entry_step_kind,
        )
        node = ComputeNodeRun(
            scope=planned.scope,
            dependency_scopes=planned.dependency_scopes,
            priority_band=priority_band,
            profile_step_index=profile_step_index,
            execution_generation=self._allocate_execution_generation(),
            bundle=bundle,
        )
        self._nodes[planned.scope] = node

    def _allocate_execution_generation(self: ComputeOrchestrator) -> int:
        generation = self._next_execution_generation
        self._next_execution_generation += 1
        return generation

    def _resolve_profile_step_index(
        self: ComputeOrchestrator,
        registration: AnalyticComputeRegistration,
        entry_step_kind: str | None,
    ) -> int:
        steps = registration.compute_profile.steps
        if entry_step_kind is None:
            return 0
        for index, step in enumerate(steps):
            if step.step_kind == entry_step_kind:
                return index
        raise ValueError(
            f"unknown entry step_kind {entry_step_kind!r} for analytic {registration.analytic_id!r}"
        )
