"""Compute orchestrator DAG scheduler with singleflight and inline execution."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from api.analytics.export_context import AnalyticQueryContext
from api.compute.dag import PlannedComputeNode, plan_compute_dag
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.orchestrator_observers import (
    InlineStartListener,
    LifecycleEventKind,
    LifecycleListener,
    NodeCompleteListener,
    NodeDispatchCommitHook,
    NodeDispatchGate,
    OrchestratorObservers,
    ReadyListener,
    ReadyQueueChangedListener,
    StepCompleteListener,
)
from api.compute.orchestrator_step_execution import (
    OrchestratorStepExecutionMixin,
    _PendingInlineExecution,
    _PendingPoolSubmission,
)
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
from api.compute.pools import (
    PRIORITY_BAND_RANK,
    ComputePriorityBand,
    ComputeWorkerPool,
    PoolSubmitter,
)
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.compute.scope_terminal_fanout import notify_process_scope_terminal
from api.compute.turn_cache import OrchestratorTurnCache
from api.compute.wire import coerce_step_result
from api.models.game import TurnInfo

NodeState = Literal[
    "waiting_deps",
    "ready",
    "running",
    "attach_inflight",
    "complete",
    "failed",
]


@dataclass(frozen=True)
class ComputeRequest:
    """One orchestrator submission for a compute scope."""

    scope: ComputeScope
    step_kind: str | None = None
    priority_band: ComputePriorityBand = "background"
    force_fresh: bool = False
    bundle: OrchestrationBundle | None = None
    ctx: AnalyticQueryContext | None = None

    def resolved_bundle(self) -> OrchestrationBundle | None:
        """Return the caller-supplied bundle, or build one from ``ctx`` for convenience."""
        if self.bundle is not None:
            return self.bundle
        if self.ctx is not None:
            return OrchestrationBundle.from_context(self.ctx)
        return None


@dataclass
class ComputeHandle:
    """Caller-visible orchestrator handle for one submission."""

    scope: ComputeScope
    _node: ComputeNodeRun
    is_waiter: bool = False
    _waiter_error: BaseException | None = field(default=None, compare=False)

    @property
    def error(self) -> BaseException | None:
        if self.is_waiter:
            return self._waiter_error
        if self._node.state == "failed":
            return self._node.error
        return None

    @property
    def state(self) -> NodeState:
        if self.is_waiter and self._node.state not in {"complete", "failed"}:
            return "attach_inflight"
        return self._node.state

    @property
    def result_wire(self) -> object | None:
        return self._node.result_wire


@dataclass
class ComputeNodeRun:
    """Mutable orchestrator state for one compute scope."""

    scope: ComputeScope
    dependency_scopes: tuple[ComputeScope, ...]
    state: NodeState = "waiting_deps"
    profile_step_index: int = 0
    step_index: int = 0
    priority_band: ComputePriorityBand = "background"
    generation_at_submit: int | None = None
    result_wire: object | None = None
    error: BaseException | None = None
    waiters: list[ComputeHandle] = field(default_factory=list)
    # Leader-retained query context / export services (see OrchestrationBundle).
    bundle: OrchestrationBundle | None = None
    # True once expensive inline/pool work has started (job wire built or handed
    # to the pool); closes the priority-adopt window for later attaches.
    execution_sealed: bool = False


@dataclass
class OrchestratorMetrics:
    """Test and diagnostics counters for orchestrator dispatch."""

    inline_executions: int = 0
    pool_submissions: int = 0
    epoch_discards: int = 0
    persist_calls: int = 0
    satisfaction_short_circuits: int = 0


@dataclass(frozen=True)
class OrchestratorNodeSnapshot:
    """Immutable copy of one node's diagnostics-visible fields."""

    scope: ComputeScope
    state: NodeState
    profile_step_index: int
    step_index: int
    priority_band: ComputePriorityBand


@dataclass(frozen=True)
class OrchestratorDiagnosticsSnapshot:
    """Immutable node and ready-queue view captured under the orchestrator lock."""

    nodes: tuple[OrchestratorNodeSnapshot, ...]
    ready_scopes: tuple[ComputeScope, ...]


class ComputeOrchestrator(OrchestratorStepExecutionMixin):
    """Process-wide DAG scheduler with singleflight per normalized compute scope.

    One instance schedules every analytic's compute work. Concurrent
    submissions for the same scope singleflight onto one ``ComputeNodeRun``:
    the first submission plans and registers the node (becoming its leader),
    later callers attach as waiters and resume from that node's terminal
    result. Each node retains the ``OrchestrationBundle`` (query context,
    export services) of whichever submission first registered it, for the
    life of the node -- later attaches with a different bundle do not change
    what wire build, persist, and satisfaction checks see.

    A waiter with a higher-priority band than the node it attaches to upgrades
    ``node.priority_band`` in place so the next enqueue/dispatch sees the
    higher band, unless the node has already sealed for execution (job wire
    built inline, or handed to the pool) -- the adopt window has closed by
    then and the waiter simply waits for the leader.

    There is no process-wide scope lease: singleflight here plus durable
    satisfaction short-circuit (``PersistencePolicy.is_satisfied``) is enough
    to avoid duplicate work for one orchestrator instance, and only one
    instance exists per process.
    """

    def __init__(
        self,
        *,
        compute_registry: Mapping[str, AnalyticComputeRegistration],
        pool_submitter: PoolSubmitter | None = None,
        worker_pool: ComputeWorkerPool | None = None,
    ) -> None:
        self._turn_cache = OrchestratorTurnCache()
        self._compute_registry = compute_registry
        self._pool_registration_id: int | None = None
        if worker_pool is not None:
            self._pool_registration_id = worker_pool.register(self)
            pool_submitter = worker_pool.submitter_for(self._pool_registration_id)
        self._pool_submitter = pool_submitter
        self._worker_pool = worker_pool
        self._nodes: dict[ComputeScope, ComputeNodeRun] = {}
        self._ready_queue: deque[ComputeScope] = deque()
        self._metrics = OrchestratorMetrics()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._observers = OrchestratorObservers(self._condition)

    def dispatch_ready_work(self) -> None:
        """Dispatch any ready nodes allowed by the current gates.

        Inline execution and pool job-wire construction run only after the
        orchestrator lock is released. Holding that lock across ``pool.submit``
        deadlocks with pool workers (pool lock then diagnostics controller lock).
        Holding it across scores/fleet job-wire builders deadlocks with the
        inference scheduler (scheduler lock then orchestrator lock).
        """
        with self._condition:
            pending_inline, pending_pool = self._dispatch()
        self._execute_pending_inlines(pending_inline)
        self._flush_pending_pool_submissions(pending_pool)
        self._observers.drain_post_lock_callbacks()

    @property
    def worker_pool(self) -> ComputeWorkerPool | None:
        return self._worker_pool

    @property
    def pool_registration_id(self) -> int | None:
        return self._pool_registration_id

    @property
    def metrics(self) -> OrchestratorMetrics:
        return self._metrics

    @property
    def turn_cache(self) -> OrchestratorTurnCache:
        return self._turn_cache

    def register_dispatch_gate(
        self,
        gate: NodeDispatchGate,
    ) -> Callable[[], None]:
        """Register a node-level gate; dispatch only if all registered gates pass.

        Gates must be side-effect free. Slot or grant consumption belongs in a
        :meth:`register_dispatch_commit_hook` so a later gate failure cannot burn
        a single-step slot.

        Returns an unregister callable that removes only this gate.
        """
        return self._observers.register_dispatch_gate(gate)

    def register_dispatch_commit_hook(
        self,
        hook: NodeDispatchCommitHook,
    ) -> Callable[[], None]:
        """Register a post-gate commit hook; called only when every gate passed.

        Returns an unregister callable that removes only this hook.
        """
        return self._observers.register_dispatch_commit_hook(hook)

    def register_node_complete_listener(
        self,
        listener: NodeCompleteListener,
    ) -> Callable[[], None]:
        """Register a node completion listener; return an unregister callable."""
        return self._observers.register_node_complete_listener(listener)

    def register_step_complete_listener(
        self,
        listener: StepCompleteListener,
    ) -> Callable[[], None]:
        """Register a step completion listener; return an unregister callable."""
        return self._observers.register_step_complete_listener(listener)

    def register_ready_listener(
        self,
        listener: ReadyListener,
    ) -> Callable[[], None]:
        """Register a ready-queue listener; return an unregister callable.

        Listeners run after the orchestrator lock is released (via post-lock
        callbacks) so observers may take other locks without nesting under the
        orchestrator condition.
        """
        return self._observers.register_ready_listener(listener)

    def register_ready_queue_listener(
        self,
        listener: ReadyQueueChangedListener,
    ) -> Callable[[], None]:
        """Register a ready-queue depth listener; return an unregister callable.

        Listeners run under the orchestrator lock with the current ready-scopes
        snapshot whenever membership may have changed (enqueue, dequeue, dispatch
        pop including ready→waiting_deps). They must not re-enter this
        orchestrator's condition. Taking the diagnostics controller lock is OK
        (same order as dispatch gates: orch → controller).
        """
        return self._observers.register_ready_queue_listener(listener)

    def register_inline_start_listener(
        self,
        listener: InlineStartListener,
    ) -> Callable[[], None]:
        """Register an inline-step start listener; return an unregister callable.

        Listeners run outside the orchestrator lock at the start of inline
        execution (before job-wire build / ``run_step``).
        """
        return self._observers.register_inline_start_listener(listener)

    def register_lifecycle_listener(
        self,
        listener: LifecycleListener,
    ) -> Callable[[], None]:
        """Register a causal lifecycle listener; return an unregister callable.

        Fired for force_fresh replace/attach, abort, epoch retry, persist-deferred
        recovery, and ignored stale pool finishes. Listeners run after the
        orchestrator lock is released.
        """
        return self._observers.register_lifecycle_listener(listener)

    @property
    def nodes(self) -> Mapping[ComputeScope, ComputeNodeRun]:
        return self._nodes

    def ready_scopes(self) -> tuple[ComputeScope, ...]:
        """Return scopes currently in the ready queue."""
        with self._condition:
            return tuple(
                scope for scope in self._ready_queue if self._nodes[scope].state == "ready"
            )

    def diagnostics_snapshot(self) -> OrchestratorDiagnosticsSnapshot:
        """Return immutable node and ready-queue data in one critical section."""
        with self._condition:
            nodes = tuple(
                OrchestratorNodeSnapshot(
                    scope=node.scope,
                    state=node.state,
                    profile_step_index=node.profile_step_index,
                    step_index=node.step_index,
                    priority_band=node.priority_band,
                )
                for node in self._nodes.values()
            )
            ready_scopes = tuple(
                scope for scope in self._ready_queue if self._nodes[scope].state == "ready"
            )
            return OrchestratorDiagnosticsSnapshot(nodes=nodes, ready_scopes=ready_scopes)

    def submit(self, request: ComputeRequest) -> ComputeHandle:
        """Submit or attach to in-flight work for one compute scope."""
        with self._condition:
            scope = request.scope
            existing = self._nodes.get(scope)
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
                    handle = self._attach_to_existing(existing, request)
                    pending_inline, pending_pool = self._dispatch()
                    should_plan = False
                else:
                    self._emit_force_fresh_lifecycle(
                        kind="force_fresh_replace",
                        node=existing,
                        request=request,
                    )
                    self._replace_terminal_node(existing)
                    should_plan = True
            else:
                should_plan = True

            if should_plan:
                bundle = self._require_bundle(request)
                self._plan_and_register(
                    scope,
                    bundle=bundle,
                    priority_band=request.priority_band,
                    entry_step_kind=request.step_kind,
                )
                for node in self._nodes.values():
                    self._refresh_node_readiness(node)
                handle = ComputeHandle(scope=scope, _node=self._nodes[scope])
                pending_inline, pending_pool = self._dispatch()
        self._execute_pending_inlines(pending_inline)
        self._flush_pending_pool_submissions(pending_pool)
        self._observers.drain_post_lock_callbacks()
        return handle

    def execute_pool_step(self, scope: ComputeScope) -> object:
        """Run the current pool step for one scope on the calling thread."""
        with self._condition:
            node = self._nodes[scope]
            if node.state != "running":
                raise RuntimeError(f"cannot execute pool step for node in state {node.state!r}")
            registration = self._compute_registry[node.scope.analytic_id]
            step = self._current_step_spec(node, registration)
            dependency_outputs = self._snapshot_dependency_outputs(node)
            run_step = registration.run_step[step.step_kind]
            builder = registration.build_step_job_wire[step.step_kind]
            node_scope = node.scope
            ctx = self._ctx_for_node(node)
        job_wire = builder(
            node_scope,
            dependency_outputs=dependency_outputs,
            ctx=ctx,
        )
        return run_step(job_wire)

    def run_until_idle(self) -> None:
        """Drain ready inline work until no ready or running nodes remain."""
        while True:
            with self._condition:
                if not self._has_pending_work():
                    break
                self._refresh_all_readiness()
                pending_inline, pending_pool = self._dispatch()
                has_running = any(node.state == "running" for node in self._nodes.values())
            self._execute_pending_inlines(pending_inline)
            self._flush_pending_pool_submissions(pending_pool)
            self._observers.drain_post_lock_callbacks()
            if has_running:
                break
        self._observers.drain_post_lock_callbacks()

    def complete_pool_step(
        self,
        scope: ComputeScope,
        *,
        result_wire: object | None = None,
        error: BaseException | None = None,
        step_kind: str | None = None,
        step_index: int | None = None,
    ) -> None:
        """Mark a pool-submitted step complete (used by worker pool integration).

        Optional ``step_kind`` / ``step_index`` come from the pool work item and are
        used when the node is no longer ``running`` (stale finish after abort/replace).
        """
        with self._condition:
            node = self._nodes.get(scope)
            if node is None:
                self._observers.notify_lifecycle(
                    "pool_finish_ignored",
                    scope,
                    detail={
                        "reason": "missing_node",
                        "poolStepKind": step_kind,
                        "poolStepIndex": step_index,
                        "hadError": error is not None,
                    },
                )
            elif node.state != "running":
                # Already aborted/cancelled/replaced while the pool worker was finishing.
                self._observers.notify_lifecycle(
                    "pool_finish_ignored",
                    scope,
                    node=node,
                    detail={
                        "reason": "node_not_running",
                        "priorState": node.state,
                        "priorStepIndex": node.step_index,
                        "priorProfileStepIndex": node.profile_step_index,
                        "poolStepKind": step_kind,
                        "poolStepIndex": step_index,
                        "hadError": error is not None,
                    },
                )
            else:
                finished_step_kind = self._current_step_spec(
                    node,
                    self._compute_registry[node.scope.analytic_id],
                ).step_kind
                finished_step_index = node.step_index
                if error is not None:
                    self._observers.notify_step_complete(
                        node,
                        finished_step_kind,
                        step_index=finished_step_index,
                        surface="pool",
                        terminal_state="failed",
                    )
                    self._fail_node(node, error)
                else:
                    self._observers.notify_step_complete(
                        node,
                        finished_step_kind,
                        step_index=finished_step_index,
                        surface="pool",
                        terminal_state="success",
                    )
                    self._after_step_success(node, result_wire)
        self._observers.drain_post_lock_callbacks()

    def abort_scope(self, scope: ComputeScope, error: BaseException) -> bool:
        """Abort a non-terminal node so a later ``force_fresh`` submit can replace it.

        Returns whether a node was aborted. No-op when the scope is absent or already
        terminal. Used when a stream row run is cancelled while orchestrator work for
        that scope is still in flight.

        Prefer :class:`ComputeScopeAbortedError` for intentional cancels: the node
        becomes ``failed`` for force_fresh replacement, but dependents do **not**
        cascade-fail (they stay ``waiting_deps`` on the singleton DAG).
        """
        with self._condition:
            node = self._nodes.get(scope)
            if node is None or node.state in {"complete", "failed"}:
                return False
            prior_state = node.state
            was_running = prior_state == "running"
            finished_step_kind: str | None = None
            finished_step_index = node.step_index
            if was_running:
                registration = self._compute_registry.get(node.scope.analytic_id)
                if registration is not None:
                    finished_step_kind = self._current_step_spec(node, registration).step_kind
                    self._observers.notify_step_complete(
                        node,
                        finished_step_kind,
                        step_index=finished_step_index,
                        surface="pool",
                        terminal_state="failed",
                    )
            self._observers.notify_lifecycle(
                "abort",
                scope,
                node=node,
                detail={
                    "reason": "abort_scope",
                    "priorState": prior_state,
                    "priorStepIndex": finished_step_index,
                    "priorProfileStepIndex": node.profile_step_index,
                    "wasRunning": was_running,
                    "stepKind": finished_step_kind,
                    "errorType": type(error).__name__,
                },
            )
            self._fail_node(node, error)
        self._observers.drain_post_lock_callbacks()
        return True

    def _emit_force_fresh_lifecycle(
        self,
        *,
        kind: LifecycleEventKind,
        node: ComputeNodeRun,
        request: ComputeRequest,
    ) -> None:
        """Record force_fresh replace vs attach (caller holds the orchestrator lock)."""
        self._observers.notify_lifecycle(
            kind,
            node.scope,
            node=node,
            detail={
                "reason": "submit_force_fresh",
                "priorState": node.state,
                "priorStepIndex": node.step_index,
                "priorProfileStepIndex": node.profile_step_index,
                "wasRunning": node.state == "running",
                "entryStepKind": request.step_kind,
                "priorityBand": request.priority_band,
            },
        )

    def _ctx_for_bundle(self, bundle: OrchestrationBundle) -> AnalyticQueryContext:
        """Return a ctx view of ``bundle`` with the process-wide turn cache spliced in."""
        game_id = bundle.game_id
        perspective = bundle.perspective
        underlying = bundle.query_context.load_turn

        def cached_load(turn_number: int) -> TurnInfo | None:
            return self._turn_cache.get(
                game_id,
                perspective,
                turn_number,
                load_turn=underlying,
            )

        return bundle.query_context_with_load_turn(cached_load)

    def _ctx_for_node(self, node: ComputeNodeRun) -> AnalyticQueryContext:
        if node.bundle is None:
            raise RuntimeError(f"compute node {node.scope!r} has no orchestration bundle")
        return self._ctx_for_bundle(node.bundle)

    def _require_bundle(self, request: ComputeRequest) -> OrchestrationBundle:
        bundle = request.resolved_bundle()
        if bundle is None:
            raise ValueError("ComputeRequest requires bundle= or ctx= for new work")
        return bundle

    def _attach_to_existing(
        self,
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
        self,
        node: ComputeNodeRun,
        priority_band: ComputePriorityBand,
    ) -> None:
        """Upgrade a non-terminal node's priority band to match a higher-priority attach.

        Closed once the node has sealed for execution: adopting after job-wire
        build has started (or after the step is handed to the pool) could race
        the in-flight work, so later attaches simply wait for that leader.
        """
        if node.execution_sealed:
            return
        if node.state not in {"waiting_deps", "ready", "running"}:
            return
        if PRIORITY_BAND_RANK[priority_band] >= PRIORITY_BAND_RANK[node.priority_band]:
            return
        node.priority_band = priority_band

    def _replace_terminal_node(self, node: ComputeNodeRun) -> None:
        if node.state not in {"complete", "failed"}:
            raise RuntimeError(f"cannot replace non-terminal node in state {node.state!r}")
        self._dequeue_ready(node.scope)
        node.waiters.clear()
        self._nodes.pop(node.scope, None)

    def _plan_and_register(
        self,
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
                bundle=bundle,
            )

    def _register_planned_node(
        self,
        planned: PlannedComputeNode,
        *,
        bundle: OrchestrationBundle,
        priority_band: ComputePriorityBand,
        entry_step_kind: str | None = None,
    ) -> None:
        if planned.scope in self._nodes:
            # Existing node keeps the bundle of whichever submission first
            # registered it -- the leader is sticky.
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
            bundle=bundle,
        )
        self._nodes[planned.scope] = node

    def _resolve_profile_step_index(
        self,
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

    def _refresh_all_readiness(self) -> None:
        for node in self._nodes.values():
            if node.state in {"complete", "failed", "running"}:
                continue
            self._refresh_node_readiness(node)

    def _refresh_node_readiness(self, node: ComputeNodeRun) -> None:
        if node.state in {"complete", "failed", "running"}:
            return
        failed_dependency_error = self._failed_dependency_error(node)
        if failed_dependency_error is not None:
            self._fail_node(node, failed_dependency_error)
            return
        if self._deps_complete(node):
            if node.state != "ready":
                node.state = "ready"
                self._enqueue_ready(node.scope)
                self._observers.notify_ready(node)
        else:
            node.state = "waiting_deps"
            self._dequeue_ready(node.scope)

    def _failed_dependency_error(self, node: ComputeNodeRun) -> BaseException | None:
        for dependency_scope in node.dependency_scopes:
            dependency = self._nodes.get(dependency_scope)
            if dependency is None or dependency.state != "failed":
                continue
            # Intentional cancel aborts must not poison dependents on the singleton DAG
            # (fleet waiting on scores). Treat as incomplete until force_fresh recreates.
            if isinstance(dependency.error, ComputeScopeAbortedError):
                continue
            return dependency.error
        return None

    def _deps_complete(self, node: ComputeNodeRun) -> bool:
        for dependency_scope in node.dependency_scopes:
            dependency = self._nodes.get(dependency_scope)
            if dependency is None or dependency.state != "complete":
                return False
        return True

    def _enqueue_ready(self, scope: ComputeScope) -> None:
        if scope not in self._ready_queue:
            self._ready_queue.append(scope)
            self._notify_ready_queue_changed()

    def _dequeue_ready(self, scope: ComputeScope) -> None:
        try:
            self._ready_queue.remove(scope)
        except ValueError:
            return
        self._notify_ready_queue_changed()

    def _current_invalidation_generation(self, node: ComputeNodeRun) -> int:
        registration = self._compute_registry[node.scope.analytic_id]
        ctx = self._ctx_for_node(node)
        return registration.persistence_policy.invalidation_generation(ctx, node.scope)

    def _is_epoch_stale(self, node: ComputeNodeRun) -> bool:
        if node.generation_at_submit is None:
            return False
        return self._current_invalidation_generation(node) != node.generation_at_submit

    def _retry_step_after_epoch_bump(self, node: ComputeNodeRun) -> None:
        self._metrics.epoch_discards += 1
        prior_step_index = node.step_index
        prior_generation = node.generation_at_submit
        current_generation = self._current_invalidation_generation(node)
        node.generation_at_submit = None
        node.state = "ready"
        node.execution_sealed = False
        self._enqueue_ready(node.scope)
        self._observers.notify_ready(node)
        self._observers.notify_lifecycle(
            "epoch_retry",
            node.scope,
            node=node,
            detail={
                "reason": "invalidation_generation_bump",
                "priorStepIndex": prior_step_index,
                "priorProfileStepIndex": node.profile_step_index,
                "generationAtSubmit": prior_generation,
                "currentGeneration": current_generation,
            },
        )
        # Never call pool.submit under the orchestrator lock (deadlocks with workers).
        self._observers.schedule_post_lock(self.dispatch_ready_work)

    def _recover_after_persist_deferred(
        self,
        node: ComputeNodeRun,
        recovery: PersistDependencyRecovery,
    ) -> None:
        """Park the node on ``waiting_deps`` and optionally force_fresh a dependency.

        Analytic ``PersistencePolicy.persist`` raises :class:`PersistDeferredError`
        when a durable write cannot complete until a dependency re-closes.
        Failing the node left dependents waiting with no wake for background DAG
        nodes (no table-stream controller). Force-freshing the declared dependency
        reopens the ENSURE edge; when it completes, readiness promotes this node.
        """
        priority_band = node.priority_band
        bundle = node.bundle
        with self._condition:
            if node.state != "running":
                return
            prior_step_index = node.step_index
            node.generation_at_submit = None
            node.error = None
            node.state = "waiting_deps"
            node.execution_sealed = False
            self._dequeue_ready(node.scope)
            self._metrics.epoch_discards += 1
            from api.compute.diagnostics.scope_key import format_compute_scope_key

            self._observers.notify_lifecycle(
                "persist_deferred",
                node.scope,
                node=node,
                detail={
                    "reason": "persist_deferred",
                    "priorStepIndex": prior_step_index,
                    "priorProfileStepIndex": node.profile_step_index,
                    "relatedScopeKey": format_compute_scope_key(recovery.dependency_scope),
                    "forceFresh": recovery.force_fresh,
                    "dependencyStepKind": recovery.step_kind,
                    "priorityBand": priority_band,
                },
            )

        if not recovery.force_fresh:
            return

        dependency_scope = recovery.dependency_scope
        step_kind = recovery.step_kind

        def _force_fresh_dependency() -> None:
            self.submit(
                ComputeRequest(
                    scope=dependency_scope,
                    priority_band=priority_band,
                    force_fresh=True,
                    step_kind=step_kind,
                    bundle=bundle,
                )
            )

        self._observers.schedule_post_lock(_force_fresh_dependency)

    def _after_step_success(self, node: ComputeNodeRun, result_wire: object | None) -> None:
        if self._is_epoch_stale(node):
            self._retry_step_after_epoch_bump(node)
            return

        step_result = coerce_step_result(result_wire)
        registration = self._compute_registry[node.scope.analytic_id]
        node.generation_at_submit = None

        if step_result.outcome == "continue":
            if step_result.payload is not None:
                node.result_wire = step_result.payload
            self._continue_node_step(node, registration)
            return

        if step_result.outcome == "persist":
            node.result_wire = step_result.payload
            self._metrics.persist_calls += 1
            # Persist must not run under the orchestrator lock: fleet refine/scores
            # probes take the inference scheduler lock, and scheduler paths call back
            # into register_dispatch_gate / dispatch_ready_work (ABBA deadlock).
            #
            # Ordering invariant (even outside the lock): persist must finish before
            # ``_complete_node``. Completing first would wake dependents / allow
            # ``has_final_ledger`` readers to observe a terminal node whose durable
            # artifact is not written yet (missed overlay, false unsatisfied probes,
            # or skipped scores reschedule decisions). Notifications returned from
            # ``persist`` run only after complete so skip-reschedule sees ``complete``.
            payload = step_result.payload

            def _persist_then_complete(
                completed_node: ComputeNodeRun = node,
                completed_payload: object = payload,
                completed_registration: AnalyticComputeRegistration = registration,
            ) -> None:
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
                        # Analytic-owned recovery: park waiting_deps and optionally
                        # force_fresh the declared dependency (e.g. open scores evidence).
                        self._recover_after_persist_deferred(
                            completed_node,
                            exc.recovery,
                        )
                        return
                    with self._condition:
                        if completed_node.state == "running":
                            self._fail_node(completed_node, exc)
                    return
                with self._condition:
                    if completed_node.state != "running":
                        return
                    self._complete_node(completed_node)
                    if post_lock_callback is not None:
                        self._observers.schedule_post_lock(post_lock_callback)

            self._observers.schedule_post_lock(_persist_then_complete)
            return

        if step_result.outcome == "complete":
            # Keep a provisional continue payload when the terminal step has none
            # (e.g. scores materialize export tree then tier_solve skip).
            if step_result.payload is not None:
                node.result_wire = step_result.payload
            self._complete_node(node)
            return

        raise RuntimeError(f"unsupported step outcome {step_result.outcome!r}")

    def _continue_node_step(
        self,
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
        node.execution_sealed = False
        self._enqueue_ready(node.scope)
        self._observers.notify_ready(node)
        # Defer dispatch so pool submit is never nested under this lock.
        self._observers.schedule_post_lock(self.dispatch_ready_work)

    def _complete_node(self, node: ComputeNodeRun) -> None:
        node.state = "complete"
        self._dequeue_ready(node.scope)
        for waiter in node.waiters:
            waiter._waiter_error = None
        node.waiters.clear()
        self._observers.notify_node_complete(node)
        completed_scope = node.scope
        completed_node = node
        self._observers.schedule_post_lock(
            lambda: self._handle_dependency_terminal(completed_scope),
        )
        self._observers.schedule_post_lock(
            lambda: notify_process_scope_terminal(completed_scope, completed_node),
        )

    def _fail_node(self, node: ComputeNodeRun, error: BaseException) -> None:
        if node.state == "failed":
            return
        node.state = "failed"
        node.error = error
        self._dequeue_ready(node.scope)
        for waiter in node.waiters:
            waiter._waiter_error = error
        node.waiters.clear()
        self._observers.notify_node_complete(node)
        completed_scope = node.scope
        completed_node = node
        self._observers.schedule_post_lock(
            lambda: self._handle_dependency_terminal(completed_scope),
        )
        self._observers.schedule_post_lock(
            lambda: notify_process_scope_terminal(completed_scope, completed_node),
        )

    def _ready_depth(self) -> int:
        return sum(1 for scope in self._ready_queue if self._nodes[scope].state == "ready")

    def _notify_ready_queue_changed(self) -> None:
        """Push the current ready-scopes snapshot to depth listeners (caller holds lock)."""
        ready_scopes = tuple(
            scope for scope in self._ready_queue if self._nodes[scope].state == "ready"
        )
        self._observers.notify_ready_queue_changed(ready_scopes)

    def _handle_dependency_terminal(self, completed_scope: ComputeScope) -> None:
        with self._condition:
            self._on_dependency_terminal(completed_scope)

    def _on_dependency_terminal(self, completed_scope: ComputeScope) -> None:
        for node in self._nodes.values():
            if completed_scope not in node.dependency_scopes:
                continue
            if node.state in {"complete", "failed", "running"}:
                continue
            self._refresh_node_readiness(node)
        # Defer dispatch: this runs under the orchestrator lock via
        # ``_handle_dependency_terminal``, and pool submit must not nest here.
        self._observers.schedule_post_lock(self.dispatch_ready_work)

    def _has_pending_work(self) -> bool:
        return any(
            node.state in {"waiting_deps", "ready", "running"} for node in self._nodes.values()
        )
