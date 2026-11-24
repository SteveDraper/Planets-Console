"""Submission, singleflight attachment, and DAG planning for ComputeOrchestrator."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, fields, replace
from enum import Enum
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_turn_fill import prepare_dependency_chain_turns
from api.compute.dag import PlannedComputeNode, force_root_for_entry_step, plan_compute_dag
from api.compute.errors import (
    ComputeRequesterEndedError,
    ComputeScopeAbortedError,
    UnresolvedSubmissionOpenError,
)
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.orchestrator_state import (
    ComputeHandle,
    ComputeNodeRun,
    ComputeRequest,
    PersistDeferral,
    ResolvedComputeRequest,
)
from api.compute.registry import AnalyticComputeRegistration
from api.compute.root_plan import IgnoredRootPlan, RootPlan
from api.compute.running_step import RunningStepDisposition
from api.compute.scope import (
    ComputeScope,
    compute_scope_to_export_scope,
    format_compute_scope_key,
)
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

    A request that already carries an open keeps its backfill choice and
    on-walk membership. Otherwise the query context's reader is called once.
    A request with no bundle cannot
    supply that reader and raises ``UnresolvedSubmissionOpenError``. The open
    turn is the explicit root when present, otherwise the scope turn. When
    the request is already resolved to that open, the same object is returned.
    """
    open_turn = submission_open_turn(request)
    carried = request.submission_open
    if carried is not None:
        resolved_open = replace(carried, open_turn=open_turn)
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


class TerminalRootReuse(Enum):
    """What a fresh submission does with a terminal node already at its root scope.

    ``CACHE_HIT``: a terminal root is reused unless the request is
    ``force_fresh`` (``submit``). ``REPLACE_TERMINAL``: a terminal root is
    replaced, because the caller already found the scope unsatisfied outside
    the lock (``ensure_scopes``).
    """

    CACHE_HIT = "cache_hit"
    REPLACE_TERMINAL = "replace_terminal"


@dataclass(frozen=True)
class NewNode:
    """A planned node a fresh root registers, with its resolved profile step index."""

    planned: PlannedComputeNode
    profile_step_index: int


@dataclass(frozen=True)
class RootRegistration:
    """Everything a fresh root will change, decided before its root plan accepts it.

    Deciding changes no orchestrator state, so a root plan that refuses the
    plan leaves the orchestrator as it was. Applying it cannot fail on the
    plan's contents: entry step indexes are resolved here.
    """

    planned: tuple[PlannedComputeNode, ...]
    # The ``force_fresh`` root being replaced; its replace is a lifecycle event.
    superseded_root: ComputeNodeRun | None
    # Every terminal node to replace: the existing root (superseded or an
    # ensure's hollow root), and planned dependencies whose durable result is gone.
    replaced_terminals: tuple[ComputeNodeRun, ...]
    # Planned nodes to register.
    new_nodes: tuple[NewNode, ...]
    # An empty plan for the root registers a synthetic ``complete`` root.
    needs_complete_root: bool


def _joins_existing(
    existing: ComputeNodeRun,
    request: ResolvedComputeRequest,
    reuse: TerminalRootReuse,
) -> bool:
    """Whether a submission joins the node already at its root scope.

    A live node is always joined. A terminal node is joined only as a cache
    hit: ``reuse`` keeps it and the request is not ``force_fresh``.
    """
    if not existing.is_terminal:
        return True
    return reuse is TerminalRootReuse.CACHE_HIT and not request.force_fresh


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
        """Submit or attach to in-flight work for one compute scope.

        Raises :class:`ComputeRequesterEndedError`, planning nothing, when
        ``request.requester`` is set and that execution is no longer live.

        Submission registers work and schedules a dispatch pass; the
        post-lock queue is drained in a ``finally``, so that pass runs before
        this returns or raises, unless another thread's drain ran it first.
        A raise inside the pass is logged by the drain and does not reach the
        caller. A root plan that raises as it closes still leaves its
        registered work dispatched.
        """
        resolved = resolve_submission_open(request)
        try:
            with self._open_root_plan(resolved) as root_plan:
                planned_request = self._prepare_root_planned_request(resolved, root_plan)
                with self._condition:
                    handle = self._submit_locked(
                        planned_request, root_plan, TerminalRootReuse.CACHE_HIT
                    )
        finally:
            self._observers.drain_post_lock_callbacks()
        return handle

    def wake_if_parked(
        self: ComputeOrchestrator,
        request: ComputeRequest,
    ) -> ComputeHandle | None:
        """Atomically wake a soft-parked scope, or no-op for every other state.

        A scope that is not parked returns before the backfill record is read.
        The wake re-checks that state under the same lock hold as the mutation.
        A wake attaches to the parked node, so it never registers a root plan.
        The attach schedules a dispatch pass, drained before this returns.
        """
        if not request.force_fresh:
            raise ValueError("wake_if_parked requires force_fresh=True")
        with self._condition:
            if not _is_parked_node(self._nodes.get(request.scope)):
                return None
        resolved = resolve_submission_open(request)
        try:
            with self._condition:
                parked = self._nodes.get(resolved.scope)
                if parked is None or not _is_parked_node(parked):
                    return None
                return self._attach_locked(parked, resolved)
        finally:
            self._observers.drain_post_lock_callbacks()

    def _open_root_plan(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
    ) -> AbstractContextManager[RootPlan]:
        """Open the root analytic's plan hook for this submission, outside the lock."""
        bundle = request.resolved_bundle()
        if bundle is None:
            return nullcontext(IgnoredRootPlan(request.submission_open))
        registration = self._compute_registry[request.scope.analytic_id]
        return registration.open_root_plan(
            request.scope,
            request.submission_open,
            self._ctx_for_bundle(bundle),
        )

    def _prepare_root_planned_request(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        root_plan: RootPlan,
    ) -> ResolvedComputeRequest:
        """Return ``request`` carrying ``root_plan``'s open, with its chain turns filled.

        Runs while ``root_plan`` is open and outside the orchestrator lock.
        """
        planned_request = replace(request, submission_open=root_plan.submission_open)
        bundle = planned_request.resolved_bundle()
        if bundle is not None:
            prepare_compute_request_dependency_chain(
                planned_request,
                ctx=self._ctx_for_bundle(bundle),
                backfill_earlier_turns=planned_request.submission_open.backfill_earlier_turns,
            )
        return planned_request

    def _submit_locked(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        root_plan: RootPlan,
        reuse: TerminalRootReuse,
    ) -> ComputeHandle:
        """Apply one submission under the orchestrator lock, and schedule a dispatch pass.

        ``request.submission_open`` is the open for this submission. Callers
        run ``resolve_submission_open`` before taking this lock, so this method
        does not read the backfill record. A live node at the scope is joined,
        and so is a terminal one that ``reuse`` keeps (:meth:`_attach_locked`).
        Otherwise a fresh root is decided (:meth:`_decide_root_registration`),
        reported to ``root_plan.accept_plan``, and only then applied. A root
        plan that raises refuses the submission and nothing changes. Submission
        marks nothing ``running``: it schedules a dispatch pass on the
        post-lock queue, which the caller drains after releasing the lock.

        A request whose ``requester`` execution is no longer live raises
        :class:`ComputeRequesterEndedError` before anything changes. The check
        runs in this hold, so an abort that lands while the submit fetched its
        dependency chain outside the lock still refuses it.
        """
        existing = self._nodes.get(request.scope)
        if existing is not None and _joins_existing(existing, request, reuse):
            return self._attach_locked(existing, request)
        self._refuse_ended_requester(request)
        registration = self._decide_root_registration(request, existing)
        root_plan.accept_plan(registration.planned)
        return self._apply_root_registration(request, registration)

    def _decide_root_registration(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        existing_root: ComputeNodeRun | None,
    ) -> RootRegistration:
        """Plan a fresh root and decide what it replaces and registers.

        Changes no orchestrator state. Caller holds the orchestrator lock.
        ``existing_root`` is the terminal node at the root scope, if any; the
        caller has decided to replace it. A planned dependency with a terminal
        node whose durable result is gone (a hollow terminal: durable wiped,
        node still ``complete``) is replaced so the chain rebuilds; a planned
        scope with any other node is kept as it is.
        """
        bundle = self._require_bundle(request)
        root_scope = request.scope
        ctx = self._ctx_for_bundle(bundle)
        planned_nodes = plan_compute_dag(
            ctx,
            root_scope.analytic_id,
            compute_scope_to_export_scope(root_scope),
            compute_registry=self._compute_registry,
            force_root=force_root_for_entry_step(request.step_kind),
            backfill_earlier_turns=request.submission_open.backfill_earlier_turns,
        )
        self.turn_cache.prefetch_planned_nodes(
            planned_nodes,
            load_turn=bundle.query_context.load_turn,
            game_id=bundle.game_id,
            perspective=bundle.perspective,
        )
        replaced_terminals: list[ComputeNodeRun] = []
        new_nodes: list[NewNode] = []
        for planned in planned_nodes:
            registration = self._compute_registry[planned.scope.analytic_id]
            is_root = planned.scope == root_scope
            existing = None if is_root else self._nodes.get(planned.scope)
            if existing is not None:
                if not existing.is_terminal or registration.persistence_policy.is_satisfied(
                    ctx, planned.scope
                ):
                    continue
                replaced_terminals.append(existing)
            entry_step_kind = request.step_kind if is_root else None
            new_nodes.append(
                NewNode(planned, self._resolve_profile_step_index(registration, entry_step_kind))
            )
        if existing_root is not None:
            replaced_terminals.append(existing_root)
        return RootRegistration(
            planned=planned_nodes,
            superseded_root=existing_root if request.force_fresh else None,
            replaced_terminals=tuple(replaced_terminals),
            new_nodes=tuple(new_nodes),
            needs_complete_root=all(new_node.planned.scope != root_scope for new_node in new_nodes),
        )

    def _apply_root_registration(
        self: ComputeOrchestrator,
        request: ResolvedComputeRequest,
        registration: RootRegistration,
    ) -> ComputeHandle:
        """Apply a decided fresh root, after its root plan accepted it. Caller holds the lock.

        Emits ``force_fresh_replace`` for a superseded root, then schedules the
        dispatch pass, so the replace precedes the replacing execution's events.
        Then replaces terminals, registers the new nodes, refreshes readiness
        across the DAG and raises the root's standing band.
        """
        if registration.superseded_root is not None:
            self._emit_force_fresh_lifecycle(
                kind="force_fresh_replace",
                node=registration.superseded_root,
                request=request,
            )
        self._observers.schedule_post_lock(self.dispatch_ready_work)
        bundle = self._require_bundle(request)
        submission_open = request.submission_open
        for terminal in registration.replaced_terminals:
            self._replace_terminal_node(terminal)
        for new_node in registration.new_nodes:
            self._nodes[new_node.planned.scope] = ComputeNodeRun(
                scope=new_node.planned.scope,
                dependency_scopes=new_node.planned.dependency_scopes,
                profile_step_index=new_node.profile_step_index,
                execution_generation=self._allocate_execution_generation(),
                bundle=bundle,
                submission_open=submission_open,
            )
        if registration.needs_complete_root:
            self._nodes[request.scope] = ComputeNodeRun(
                scope=request.scope,
                dependency_scopes=(),
                state="complete",
                execution_generation=self._allocate_execution_generation(),
                bundle=bundle,
                submission_open=submission_open,
            )
        for node in self._nodes.values():
            self._refresh_node_readiness(node)
        root = self._nodes[request.scope]
        # The request raises only its own scope's standing band. Its
        # dependencies take their band from it through the pass derivation.
        root.raise_standing_band(request.priority_band)
        return ComputeHandle(scope=request.scope, _node=root, _observers=self._observers)

    def _attach_locked(
        self: ComputeOrchestrator,
        existing: ComputeNodeRun,
        request: ResolvedComputeRequest,
    ) -> ComputeHandle:
        """Join ``existing`` for ``request``, and schedule a dispatch pass.

        Caller holds the orchestrator lock. Refuses an ended requester first.
        A ``force_fresh`` join emits ``force_fresh_attach`` before the pass is
        scheduled, so the event precedes the joined execution's step events.
        A ``force_fresh`` join then resolves readiness once: a parked node
        wakes; a waiting or ready node is refreshed, since its dependencies may
        have settled without reaching it (e.g. evidence-close ``force_fresh``
        after scores completed); a running node is left alone. The request
        raises only the joined scope's standing band.
        """
        self._refuse_ended_requester(request)
        if request.force_fresh:
            self._emit_force_fresh_lifecycle(
                kind="force_fresh_attach",
                node=existing,
                request=request,
            )
        self._observers.schedule_post_lock(self.dispatch_ready_work)
        if request.force_fresh:
            if existing.state == "parked":
                self._wake_parked_node(existing)
            else:
                self._refresh_node_readiness(existing)
            if existing.state == "waiting_deps":
                self._schedule_recreate_aborted_dependencies(existing)
        handle = self._attach_to_existing(existing, request)
        existing.raise_standing_band(request.priority_band)
        return handle

    def _refuse_ended_requester(
        self: ComputeOrchestrator,
        request: ComputeRequest,
    ) -> None:
        """Raise when ``request`` belongs to a node execution that is no longer live.

        Caller holds the orchestrator lock. A request with no requester passes.
        A refusal records a ``dependency_submit_refused`` lifecycle event on the
        requester's execution, naming the refused dependency scope.
        """
        requester = request.requester
        if requester is None:
            return
        generation = requester.execution_generation
        node = self._nodes.get(requester.scope)
        if node is not None and node.is_live_execution(generation):
            return
        self._observers.notify_lifecycle(
            "dependency_submit_refused",
            requester.scope,
            execution_generation=generation,
            node=node if node is not None and node.execution_generation == generation else None,
            detail={
                "reason": "requester_ended",
                "relatedScopeKey": format_compute_scope_key(request.scope),
                "dependencyStepKind": request.step_kind,
                "forceFresh": request.force_fresh,
            },
        )
        raise ComputeRequesterEndedError(requester)

    def _submit_dependencies(
        self: ComputeOrchestrator,
        requests: Sequence[ComputeRequest],
    ) -> None:
        """Submit, in order, the dependency submits one node execution queued post-lock.

        Every request names that execution as its ``requester``. Once one is
        refused because the execution ended, the rest would be refused too, so
        they are not submitted. A refusal is the requester's end, not a failure,
        and is the one ``ComputeRequesterEndedError`` handling for every
        dependency submit. Any other error propagates to the caller.
        """
        try:
            for request in requests:
                self.submit(request)
        except ComputeRequesterEndedError:
            return

    def _submit_recovery_dependency(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        generation: int,
        deferral: PersistDeferral,
        request: ComputeRequest,
    ) -> None:
        """Submit ``node``'s persist-deferred recovery ``request``, queued post-lock.

        ``generation`` is the execution that demoted ``node`` and ``deferral``
        the ``last_persist_deferral`` it recorded. A submit that registers needs
        nothing more: the replacement makes the marker inert. A refusal is
        handled as for every dependency submit (:meth:`_submit_dependencies`).
        Any other error settles ``node`` by
        :meth:`_settle_failed_recovery_submit` and is re-raised, so the
        post-lock drain logs it.
        """
        try:
            self._submit_dependencies((request,))
        except Exception as error:
            self._settle_failed_recovery_submit(node, generation, deferral, error)
            raise

    def _settle_failed_recovery_submit(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        generation: int,
        deferral: PersistDeferral,
        error: BaseException,
    ) -> None:
        """Fail ``node`` with ``error`` when its raised recovery submit registered no replacement.

        Takes the orchestrator lock. The DAG decides, not where ``error`` came
        from, since a submit can raise after it registered. ``node`` fails only
        while it is still the scope's node, live as ``generation``, in
        ``waiting_deps`` with ``deferral`` still its last deferral, and the
        deferral's dependency scope holds no node its readiness counts
        (:meth:`_readiness_dependency`): none at all, or still the superseded
        execution. Otherwise ``node`` is left alone: it settles
        on the replacement or on the live dependency it waits on, or it has
        moved on. A failed node's marker is never read again, so it needs no
        clear. ``_fail_node`` releases the node's waiters with ``error``,
        publishes its outcome, and cascades ``error`` to waiting dependents,
        whose dispatch pass it schedules.
        """
        with self._condition:
            if (
                self._nodes.get(node.scope) is node
                and node.is_live_execution(generation)
                and node.state == "waiting_deps"
                and node.last_persist_deferral is deferral
                and self._readiness_dependency(node, deferral.dependency_scope) is None
            ):
                self._fail_node(node, error)

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
        A recreated dependency takes its band from the waiting dependents.
        Dependencies are read through :meth:`_readiness_dependency`, so one a
        waiter superseded is left to that waiter's own recovery submit.
        Caller holds the orchestrator lock; submits run after release, with
        ``node``'s execution as their requester, so none is planned once that
        execution has ended.
        """
        to_recreate: dict[ComputeScope, tuple[OrchestrationBundle, SubmissionOpen]] = {}
        seen: set[ComputeScope] = set()
        stack = [node]
        while stack:
            current = stack.pop()
            if current.scope in seen:
                continue
            seen.add(current.scope)
            for dependency_scope in current.dependency_scopes:
                dependency = self._readiness_dependency(current, dependency_scope)
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
                    to_recreate[dependency_scope] = (bundle, dependency.submission_open)
                elif dependency.state == "waiting_deps":
                    stack.append(dependency)
        if not to_recreate:
            return

        requester = node.execution_ref
        recreate_requests = tuple(
            ComputeRequest(
                scope=scope,
                force_fresh=True,
                bundle=bundle,
                submission_open=submission_open,
                requester=requester,
            )
            for scope, (bundle, submission_open) in to_recreate.items()
        )
        self._observers.schedule_post_lock(lambda: self._submit_dependencies(recreate_requests))

    def _attach_to_existing(
        self: ComputeOrchestrator,
        node: ComputeNodeRun,
        request: ResolvedComputeRequest,
    ) -> ComputeHandle:
        if node.is_terminal:
            return ComputeHandle(
                scope=node.scope,
                _node=node,
                _observers=self._observers,
            )
        self._adopt_rooted_open_turn(node, request)
        # A root attach needs the node again; a planned join instead adds the
        # dependent edge the start-or-requeue gate derives "needed" from.
        node.running_step = RunningStepDisposition.CONTINUE
        handle = ComputeHandle(
            scope=node.scope,
            _node=node,
            is_waiter=True,
            _observers=self._observers,
        )
        node.waiters.append(handle)
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

    def _replace_terminal_node(self: ComputeOrchestrator, node: ComputeNodeRun) -> None:
        if not node.is_terminal:
            raise RuntimeError(f"cannot replace non-terminal node in state {node.state!r}")
        self._dequeue_ready(node.scope)
        node.waiters.clear()
        self._nodes.pop(node.scope, None)

    def _allocate_execution_generation(self: ComputeOrchestrator) -> int:
        generation = self._next_execution_generation
        self._next_execution_generation += 1
        return generation

    def _resolve_profile_step_index(
        self: ComputeOrchestrator,
        registration: AnalyticComputeRegistration,
        entry_step_kind: str | None,
    ) -> int:
        if entry_step_kind is None:
            return 0
        profile = registration.compute_profile
        if not profile.has_step_kind(entry_step_kind):
            raise ValueError(
                f"unknown entry step_kind {entry_step_kind!r} "
                f"for analytic {registration.analytic_id!r}"
            )
        return profile.step_kinds.index(entry_step_kind)
