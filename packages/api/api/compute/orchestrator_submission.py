"""Submission, singleflight attachment, and DAG planning for ComputeOrchestrator."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_turn_fill import prepare_dependency_chain_turns
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.on_walk import (
    prepare_absent_on_walk_mark,
    remember_on_walk_from_plan,
    rollback_absent_on_walk_mark,
)
from api.compute.dag import (
    PlannedComputeNode,
    earliest_planned_turn,
    force_root_for_entry_step,
    plan_compute_dag,
)
from api.compute.errors import ComputeScopeAbortedError, UnresolvedSubmissionOpenError
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.orchestrator_pending import PendingInlineExecution, PendingPoolSubmission
from api.compute.orchestrator_state import (
    ComputeHandle,
    ComputeNodeRun,
    ComputeRequest,
    ResolvedComputeRequest,
)
from api.compute.pools import PRIORITY_BAND_RANK, ComputePriorityBand
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.compute.submission_open import SubmissionOpen

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator


def _concrete_scope_turn(turn: object) -> int | None:
    if isinstance(turn, bool) or not isinstance(turn, int):
        return None
    return turn


def submission_open_turn(request: ComputeRequest) -> int | None:
    """Root turn carried onto every node this submission plans.

    An explicit ``request.submission_open.open_turn`` wins so a resubmitted hop
    keeps the root it was planned under. Otherwise the request scope's turn is
    the root.
    """
    carried = request.submission_open
    if carried is not None and carried.open_turn is not None:
        return carried.open_turn
    return _concrete_scope_turn(request.scope.turn)


def _with_resolved_open(
    request: ComputeRequest,
    submission_open: SubmissionOpen,
) -> ResolvedComputeRequest:
    """Return ``request`` carrying ``submission_open``.

    A request already resolved to that open is returned unchanged.
    """
    if isinstance(request, ResolvedComputeRequest):
        if request.submission_open == submission_open:
            return request
        return replace(request, submission_open=submission_open)
    values = {item.name: getattr(request, item.name) for item in fields(ComputeRequest)}
    values["submission_open"] = submission_open
    return ResolvedComputeRequest(**values)


def resolve_submission_open(request: ComputeRequest) -> ResolvedComputeRequest:
    """Return the request carrying its submission open.

    A request that already carries a backfill choice keeps it. Otherwise the
    query context's reader is called once. A request with no bundle cannot
    supply that reader and raises ``UnresolvedSubmissionOpenError``. The open
    turn is the explicit root when present, otherwise the scope turn. When
    the request is already resolved to that open, the same object is returned.
    """
    open_turn = submission_open_turn(request)
    carried = request.submission_open
    if carried is not None:
        resolved_open = SubmissionOpen(
            open_turn=open_turn,
            backfill_earlier_turns=carried.backfill_earlier_turns,
        )
    else:
        bundle = request.resolved_bundle()
        if bundle is None:
            raise UnresolvedSubmissionOpenError(
                "ComputeRequest has no submission open and no orchestration bundle "
                "to read the backfill choice"
            )
        enabled = bundle.query_context.backfill_earlier_turns_enabled()
        resolved_open = SubmissionOpen(open_turn=open_turn, backfill_earlier_turns=enabled)
    return _with_resolved_open(request, resolved_open)


@dataclass(frozen=True)
class _FreshRootPlan:
    """A submission that registered a new root plan, including an empty one.

    ``earliest_turn`` is None when that plan scheduled no scopes. A join does
    not produce a fresh plan.
    """

    request: ResolvedComputeRequest
    earliest_turn: int | None


def _is_parked_node(node: ComputeNodeRun | None) -> bool:
    """Whether ``wake_if_parked`` may wake this node."""
    return node is not None and node.state == "parked"


def prepare_compute_request_dependency_chain(
    request: ComputeRequest,
    *,
    ctx: AnalyticQueryContext | None = None,
    backfill_earlier_turns: bool,
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
        force_root=force_root_for_entry_step(request.step_kind),
        backfill_earlier_turns=backfill_earlier_turns,
    )


class OrchestratorSubmissionMixin:
    """Submit, wake, attach, and plan compute work under the orchestrator lock."""

    def submit(self: ComputeOrchestrator, request: ComputeRequest) -> ComputeHandle:
        """Submit or attach to in-flight work for one compute scope."""
        resolved = resolve_submission_open(request)
        established = self._prepare_on_walk_mark(resolved)
        try:
            bundle = resolved.resolved_bundle()
            if bundle is not None:
                spliced = self._ctx_for_bundle(bundle)
                prepare_compute_request_dependency_chain(
                    resolved,
                    ctx=spliced,
                    backfill_earlier_turns=resolved.submission_open.backfill_earlier_turns,
                )
            with self._condition:
                submission = self._submit_locked(resolved, wake_if_parked_only=False)
            if submission is None:
                raise RuntimeError("submit_locked returned None without wake_if_parked_only")
            handle, pending_inline, pending_pool, fresh_root = submission
            self._settle_on_walk_mark(resolved, fresh_root, established)
            established = None
            return self._finish_submission((handle, pending_inline, pending_pool))
        finally:
            if established is not None:
                self._rollback_prepared_on_walk_mark(resolved, established)

    def wake_if_parked(
        self: ComputeOrchestrator,
        request: ComputeRequest,
    ) -> ComputeHandle | None:
        """Atomically wake a soft-parked scope, or no-op for every other state.

        A scope that is not parked returns before the backfill record is read.
        The wake re-checks that state under the same lock hold as the mutation.
        """
        if not request.force_fresh:
            raise ValueError("wake_if_parked requires force_fresh=True")
        with self._condition:
            if not _is_parked_node(self._nodes.get(request.scope)):
                return None
        resolved = resolve_submission_open(request)
        established = self._prepare_on_walk_mark(resolved)
        try:
            with self._condition:
                submission = self._submit_locked(resolved, wake_if_parked_only=True)
            if submission is None:
                return None
            handle, pending_inline, pending_pool, fresh_root = submission
            self._settle_on_walk_mark(resolved, fresh_root, established)
            established = None
            return self._finish_submission((handle, pending_inline, pending_pool))
        finally:
            if established is not None:
                self._rollback_prepared_on_walk_mark(resolved, established)

    def _prepare_on_walk_mark(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        *,
        replace_terminal: bool = False,
    ) -> FleetEvidenceMark | None:
        """Establish an absent on-walk mark before the plan. No long lock hold.

        The fresh-root check takes the condition only for the node lookup.
        The mark write runs after that lock is released. An existing mark is
        left for the plan to read. A join or an empty plan rolls this write back.
        """
        if not request.submission_open.backfill_earlier_turns:
            return None
        if not self._submission_plans_fresh_root(request, replace_terminal=replace_terminal):
            return None
        return prepare_absent_on_walk_mark(self._request_with_spliced_ctx(request))

    def _submission_plans_fresh_root(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        *,
        replace_terminal: bool = False,
    ) -> bool:
        """Whether this submission will register a new root instead of joining.

        A non-terminal node is a join. A terminal node is replaced when
        ``force_fresh`` is set, or when the caller drops hollow terminals.
        """
        with self._condition:
            existing = self._nodes.get(request.scope)
            if existing is None:
                return True
            if not existing.is_terminal:
                return False
            return bool(request.force_fresh or replace_terminal)

    def _settle_on_walk_mark(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        fresh_root: _FreshRootPlan | None,
        established: FleetEvidenceMark | None,
    ) -> None:
        """Widen from the registered plan, or roll back an unused absent-mark write.

        An empty plan and a join both roll back. An existing mark is widened
        only when the registered plan scheduled a turn.
        """
        if fresh_root is not None and fresh_root.earliest_turn is not None:
            remember_on_walk_from_plan(
                self._request_with_spliced_ctx(fresh_root.request),
                earliest_turn=fresh_root.earliest_turn,
            )
            return
        if established is None:
            return
        rollback_request = fresh_root.request if fresh_root is not None else request
        self._rollback_prepared_on_walk_mark(rollback_request, established)

    def _rollback_prepared_on_walk_mark(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        established: FleetEvidenceMark,
    ) -> None:
        rollback_absent_on_walk_mark(self._request_with_spliced_ctx(request), established)

    def _request_with_spliced_ctx(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
    ) -> ResolvedComputeRequest:
        bundle = request.resolved_bundle()
        if bundle is None:
            return request
        return replace(request, bundle=None, ctx=self._ctx_for_bundle(bundle))

    def _submit_locked(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        *,
        wake_if_parked_only: bool,
    ) -> (
        tuple[
            ComputeHandle,
            tuple[PendingInlineExecution, ...],
            tuple[PendingPoolSubmission, ...],
            _FreshRootPlan | None,
        ]
        | None
    ):
        """Apply one submission under the orchestrator lock.

        ``request.submission_open`` is the open for this submission. Callers
        run ``resolve_submission_open`` before taking this lock, so this method
        does not read the backfill record.
        """
        scope = request.scope
        existing = self._nodes.get(scope)
        if wake_if_parked_only and not _is_parked_node(existing):
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
                return handle, pending_inline, pending_pool, None
            self._emit_force_fresh_lifecycle(
                kind="force_fresh_replace",
                node=existing,
                request=request,
            )
            self._replace_terminal_node(existing)
        handle, pending_inline, pending_pool, planned = self._plan_submission_locked(request)
        return (
            handle,
            pending_inline,
            pending_pool,
            _FreshRootPlan(request=request, earliest_turn=earliest_planned_turn(planned)),
        )

    def _plan_submission_locked(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
    ) -> tuple[
        ComputeHandle,
        tuple[PendingInlineExecution, ...],
        tuple[PendingPoolSubmission, ...],
        tuple[PlannedComputeNode, ...],
    ]:
        """Plan a fresh scope and select its first dispatchable work."""
        submission_open = request.submission_open
        scope = request.scope
        bundle = self._require_bundle(request)
        planned = self._plan_and_register(
            scope,
            bundle=bundle,
            priority_band=request.priority_band,
            entry_step_kind=request.step_kind,
            submission_open=submission_open,
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
            planned,
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
        A ``force_fresh`` attach of a ``waiting_deps`` waiter walks the
        ``waiting_deps`` chain and recreates abort-failed dependencies so a
        later-turn fleet attach can restart aborted prior-turn scores.
        Do not recreate on abort itself -- that would fight an in-flight cancel.
        Caller holds the orchestrator lock; submits run after release.
        """
        to_recreate: dict[
            ComputeScope,
            tuple[OrchestrationBundle, ComputePriorityBand, SubmissionOpen],
        ] = {}
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
                    to_recreate[dependency_scope] = (
                        bundle,
                        node.priority_band,
                        dependency.submission_open,
                    )
                elif dependency.state == "waiting_deps":
                    stack.append(dependency)
        if not to_recreate:
            return

        def _recreate() -> None:
            for scope, (bundle, priority_band, submission_open) in to_recreate.items():
                self.submit(
                    ComputeRequest(
                        scope=scope,
                        priority_band=priority_band,
                        force_fresh=True,
                        bundle=bundle,
                        submission_open=submission_open,
                    )
                )

        self._observers.schedule_post_lock(_recreate)

    def _attach_to_existing(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        request: ResolvedComputeRequest,
    ) -> ComputeHandle:
        if node.is_terminal:
            return ComputeHandle(
                scope=node.scope,
                _node=node,
                _condition=self._condition,
            )
        self._adopt_rooted_open_turn(node, request)
        handle = ComputeHandle(
            scope=node.scope,
            _node=node,
            is_waiter=True,
            _condition=self._condition,
        )
        node.waiters.append(handle)
        self._maybe_adopt_priority(node, request.priority_band)
        return handle

    def _adopt_rooted_open_turn(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        request: ResolvedComputeRequest,
    ) -> None:
        """A submission that roots at this scope owns the node's open turn.

        Joining any other in-flight node leaves the open it was planned with.
        The backfill choice the node started with stays with it. The open turn
        is the one already resolved onto this submission.
        """
        open_turn = request.submission_open.open_turn
        if open_turn is None or node.scope.turn != open_turn:
            return
        if node.submission_open.open_turn == open_turn:
            return
        node.submission_open = replace(node.submission_open, open_turn=open_turn)

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
        submission_open: SubmissionOpen,
    ) -> tuple[PlannedComputeNode, ...]:
        export_scope = compute_scope_to_export_scope(root_scope)
        ctx = self._ctx_for_bundle(bundle)
        planned_nodes = plan_compute_dag(
            ctx,
            root_scope.analytic_id,
            export_scope,
            compute_registry=self._compute_registry,
            force_root=force_root_for_entry_step(entry_step_kind),
            backfill_earlier_turns=submission_open.backfill_earlier_turns,
        )
        self.turn_cache.prefetch_planned_nodes(
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
                submission_open=submission_open,
            )
        if root_scope not in self._nodes:
            self._nodes[root_scope] = ComputeNodeRun(
                scope=root_scope,
                dependency_scopes=(),
                state="complete",
                priority_band=priority_band,
                execution_generation=self._allocate_execution_generation(),
                bundle=bundle,
                submission_open=submission_open,
            )
        return planned_nodes

    def _register_planned_node(
        self: ComputeOrchestrator,
        planned: PlannedComputeNode,
        *,
        bundle: OrchestrationBundle,
        priority_band: ComputePriorityBand,
        entry_step_kind: str | None = None,
        submission_open: SubmissionOpen,
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
            submission_open=submission_open,
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
