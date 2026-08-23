"""Submission, singleflight attachment, and DAG planning for ComputeOrchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_turn_fill import prepare_dependency_chain_turns
from api.compute.dag import PlannedComputeNode, plan_compute_dag
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.orchestrator_pending import PendingInlineExecution, PendingPoolSubmission
from api.compute.orchestrator_state import ComputeHandle, ComputeNodeRun, ComputeRequest
from api.compute.pools import PRIORITY_BAND_RANK, ComputePriorityBand
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope, compute_scope_to_export_scope

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator


def prepare_compute_request_dependency_chain(
    request: ComputeRequest,
    *,
    ctx: AnalyticQueryContext | None = None,
) -> None:
    """Fetch missing ENSURE_DEPENDENCIES turns before DAG plan (no orchestrator lock).

    Prefer the orchestrator's cache-spliced ``ctx`` so chain-fill walks share the
    process-wide turn cache with later ``plan_compute_dag`` / prefetch.
    """
    bundle = request.resolved_bundle()
    if bundle is None:
        return
    query_ctx = ctx if ctx is not None else bundle.query_context
    prepare_dependency_chain_turns(
        query_ctx,
        request.scope.analytic_id,
        compute_scope_to_export_scope(request.scope),
    )


class OrchestratorSubmissionMixin:
    """Submit, wake, attach, and plan compute work under the orchestrator lock."""

    def submit(self: ComputeOrchestrator, request: ComputeRequest) -> ComputeHandle:
        """Submit or attach to in-flight work for one compute scope."""
        bundle = request.resolved_bundle()
        if bundle is not None:
            prepare_compute_request_dependency_chain(
                request,
                ctx=self._ctx_for_bundle(bundle),
            )
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
            tuple[PendingInlineExecution, ...],
            tuple[PendingPoolSubmission, ...],
        ]
        | None
    ):
        """Apply one submission under the orchestrator lock."""
        scope = request.scope
        existing = self._nodes.get(scope)
        if wake_if_parked_only and (existing is None or existing.state != "parked"):
            return None

        pending_inline: tuple[PendingInlineExecution, ...] = ()
        pending_pool: tuple[PendingPoolSubmission, ...] = ()
        if existing is not None:
            if not (request.force_fresh and existing.is_terminal):
                if request.force_fresh:
                    self._emit_force_fresh_lifecycle(
                        kind="force_fresh_attach",
                        node=existing,
                        request=request,
                    )
                    self._maybe_wake_parked_node(existing)
                    # Parked wake is handled above. ``waiting_deps`` / ``ready`` still
                    # need a readiness refresh when deps are already terminal (e.g.
                    # evidence-close force_fresh after scores completed but the
                    # dependent missed the dependency-terminal callback).
                    if existing.state in {"waiting_deps", "ready"}:
                        self._refresh_node_readiness(existing)
                        if existing.state == "waiting_deps":
                            self._schedule_recreate_aborted_dependencies(existing)
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
        tuple[PendingInlineExecution, ...],
        tuple[PendingPoolSubmission, ...],
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
        return (
            ComputeHandle(
                scope=scope,
                _node=self._nodes[scope],
                _condition=self._condition,
            ),
            *self._dispatch(),
        )

    def _finish_submission(
        self: ComputeOrchestrator,
        submission: tuple[
            ComputeHandle,
            tuple[PendingInlineExecution, ...],
            tuple[PendingPoolSubmission, ...],
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

    def _schedule_recreate_aborted_dependencies(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
    ) -> None:
        """Replace abort-failed deps reachable through ``waiting_deps`` waiters.

        Abort does not cascade-fail dependents (fleet waiting on cancelled scores).
        A later ``force_fresh`` attach of the waiter used to no-op while those
        deps stayed ``failed``, leaving the DAG idle. Walk the ``waiting_deps``
        chain so a later-turn fleet attach can restart aborted prior-turn scores.
        Do not recreate on abort itself -- that would fight an in-flight cancel.
        Caller holds the orchestrator lock; submits run after release.
        """
        to_recreate: dict[ComputeScope, tuple[OrchestrationBundle, ComputePriorityBand]] = {}
        seen: set[ComputeScope] = set()
        stack = [node]
        while stack:
            current = stack.pop()
            if current.scope in seen:
                continue
            seen.add(current.scope)
            for dependency_scope in current.dependency_scopes:
                dependency = self._nodes.get(dependency_scope)
                if dependency is None:
                    continue
                if dependency.state == "failed" and isinstance(
                    dependency.error, ComputeScopeAbortedError
                ):
                    if dependency_scope in to_recreate:
                        continue
                    bundle = dependency.bundle if dependency.bundle is not None else node.bundle
                    if bundle is None:
                        continue
                    to_recreate[dependency_scope] = (bundle, node.priority_band)
                elif dependency.state == "waiting_deps":
                    stack.append(dependency)
        if not to_recreate:
            return

        def _recreate() -> None:
            for scope, (bundle, priority_band) in to_recreate.items():
                self.submit(
                    ComputeRequest(
                        scope=scope,
                        priority_band=priority_band,
                        force_fresh=True,
                        bundle=bundle,
                    )
                )

        self._observers.schedule_post_lock(_recreate)

    def _attach_to_existing(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        request: ComputeRequest,
    ) -> ComputeHandle:
        if node.is_terminal:
            return ComputeHandle(
                scope=node.scope,
                _node=node,
                _condition=self._condition,
            )
        handle = ComputeHandle(
            scope=node.scope,
            _node=node,
            is_waiter=True,
            _condition=self._condition,
        )
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
        if not node.allows_priority_adopt:
            return
        if PRIORITY_BAND_RANK[priority_band] >= PRIORITY_BAND_RANK[node.priority_band]:
            return
        node.priority_band = priority_band

    def _replace_terminal_node(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        if not node.is_terminal:
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
        # Hollow terminals on the planned DAG (root or deps): durable wipe left
        # orchestrator ``complete`` nodes that ``_register_planned_node`` would
        # otherwise keep. Drop unsatisfied terminals so the chain rebuilds -- not
        # only the ensure root (see ensure_scope hollow-root eviction).
        for planned in planned_nodes:
            existing = self._nodes.get(planned.scope)
            if existing is not None and existing.is_terminal:
                registration = self._compute_registry[planned.scope.analytic_id]
                if not registration.persistence_policy.is_satisfied(ctx, planned.scope):
                    self._replace_terminal_node(existing)
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
