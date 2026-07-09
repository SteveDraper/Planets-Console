"""Compute orchestrator DAG scheduler with singleflight and inline execution."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from api.analytics.export_context import AnalyticQueryContext
from api.compute.dag import PlannedComputeNode, plan_compute_dag
from api.compute.pools import ComputePriorityBand, ComputeWorkerPool, PoolSubmitter
from api.compute.profile import ComputeStepSpec
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.compute.turn_cache import OrchestratorTurnCache
from api.compute.wire import DependencyOutputs, coerce_step_result

NodeCompleteListener = Callable[[ComputeScope, "ComputeNodeRun"], None]
StepCompleteListener = Callable[
    [ComputeScope, "ComputeNodeRun", str, Literal["inline", "pool"], Literal["success", "failed"]],
    None,
]
NodeDispatchGate = Callable[["ComputeNodeRun"], bool]
PostLockCallback = Callable[[], None]

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


@dataclass
class OrchestratorMetrics:
    """Test and diagnostics counters for orchestrator dispatch."""

    inline_executions: int = 0
    pool_submissions: int = 0
    epoch_discards: int = 0
    persist_calls: int = 0


class ComputeOrchestrator:
    """DAG scheduler with singleflight per normalized compute scope."""

    def __init__(
        self,
        ctx: AnalyticQueryContext,
        *,
        compute_registry: Mapping[str, AnalyticComputeRegistration],
        pool_submitter: PoolSubmitter | None = None,
        worker_pool: ComputeWorkerPool | None = None,
    ) -> None:
        self._ctx = ctx
        self._turn_cache = OrchestratorTurnCache(ctx.load_turn)
        self._cached_ctx = replace(ctx, load_turn=self._turn_cache.get)
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
        self._node_complete_listeners: list[NodeCompleteListener] = []
        self._step_complete_listeners: list[StepCompleteListener] = []
        self._dispatch_gates: list[NodeDispatchGate] = []
        self._post_lock_callbacks: list[PostLockCallback] = []

    def dispatch_ready_work(self) -> None:
        """Dispatch any ready nodes allowed by the current gates."""
        with self._condition:
            self._dispatch()
        self._drain_post_lock_callbacks()

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

        Returns an unregister callable that removes only this gate.
        """
        with self._condition:
            self._dispatch_gates.append(gate)

        def unregister() -> None:
            with self._condition:
                try:
                    self._dispatch_gates.remove(gate)
                except ValueError:
                    return

        return unregister

    def register_node_complete_listener(
        self,
        listener: NodeCompleteListener,
    ) -> Callable[[], None]:
        """Register a node completion listener; return an unregister callable."""
        with self._condition:
            self._node_complete_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._node_complete_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def register_step_complete_listener(
        self,
        listener: StepCompleteListener,
    ) -> Callable[[], None]:
        """Register a step completion listener; return an unregister callable."""
        with self._condition:
            self._step_complete_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._step_complete_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    @property
    def nodes(self) -> Mapping[ComputeScope, ComputeNodeRun]:
        return self._nodes

    def ready_scopes(self) -> tuple[ComputeScope, ...]:
        """Return scopes currently in the ready queue."""
        with self._condition:
            return tuple(
                scope for scope in self._ready_queue if self._nodes[scope].state == "ready"
            )

    def submit(self, request: ComputeRequest) -> ComputeHandle:
        """Submit or attach to in-flight work for one compute scope."""
        with self._condition:
            scope = request.scope
            existing = self._nodes.get(scope)
            if existing is not None:
                if not (request.force_fresh and existing.state in {"complete", "failed"}):
                    handle = self._attach_to_existing(existing)
                    self._dispatch()
                    should_plan = False
                else:
                    self._replace_terminal_node(existing)
                    should_plan = True
            else:
                should_plan = True

            if should_plan:
                self._plan_and_register(
                    scope,
                    priority_band=request.priority_band,
                    entry_step_kind=request.step_kind,
                )
                for node in self._nodes.values():
                    self._refresh_node_readiness(node)
                handle = ComputeHandle(scope=scope, _node=self._nodes[scope])
                self._dispatch()
        self._drain_post_lock_callbacks()
        return handle

    def execute_pool_step(self, scope: ComputeScope) -> object:
        """Run the current pool step for one scope on the calling thread."""
        with self._condition:
            node = self._nodes[scope]
            if node.state != "running":
                raise RuntimeError(f"cannot execute pool step for node in state {node.state!r}")
            registration = self._compute_registry[node.scope.analytic_id]
            step = self._current_step_spec(node, registration)
            job_wire = self._build_job_wire(node, registration, step)
            run_step = registration.run_step[step.step_kind]
        return run_step(job_wire)

    def run_until_idle(self) -> None:
        """Drain ready inline work until no ready or running nodes remain."""
        while True:
            with self._condition:
                if not self._has_pending_work():
                    break
                self._refresh_all_readiness()
                self._dispatch()
                if any(node.state == "running" for node in self._nodes.values()):
                    break
            self._drain_post_lock_callbacks()
        self._drain_post_lock_callbacks()

    def complete_pool_step(
        self,
        scope: ComputeScope,
        *,
        result_wire: object | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Mark a pool-submitted step complete (used by worker pool integration)."""
        with self._condition:
            node = self._nodes[scope]
            if node.state != "running":
                raise RuntimeError(f"cannot complete pool step for node in state {node.state!r}")
            if error is not None:
                step_kind = self._current_step_spec(
                    node,
                    self._compute_registry[node.scope.analytic_id],
                ).step_kind
                self._notify_step_complete(
                    node,
                    step_kind,
                    surface="pool",
                    terminal_state="failed",
                )
                self._fail_node(node, error)
            else:
                step_kind = self._current_step_spec(
                    node,
                    self._compute_registry[node.scope.analytic_id],
                ).step_kind
                self._notify_step_complete(
                    node,
                    step_kind,
                    surface="pool",
                    terminal_state="success",
                )
                self._after_step_success(node, result_wire)
        self._drain_post_lock_callbacks()

    def _attach_to_existing(self, node: ComputeNodeRun) -> ComputeHandle:
        if node.state in {"complete", "failed"}:
            return ComputeHandle(scope=node.scope, _node=node)
        handle = ComputeHandle(scope=node.scope, _node=node, is_waiter=True)
        node.waiters.append(handle)
        return handle

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
        priority_band: ComputePriorityBand,
        entry_step_kind: str | None = None,
    ) -> None:
        export_scope = compute_scope_to_export_scope(root_scope)
        planned_nodes = plan_compute_dag(
            self._cached_ctx,
            root_scope.analytic_id,
            export_scope,
            compute_registry=self._compute_registry,
            force_root=entry_step_kind is not None,
        )
        self._turn_cache.prefetch_planned_nodes(planned_nodes)
        for planned in planned_nodes:
            self._register_planned_node(
                planned,
                priority_band=priority_band,
                entry_step_kind=entry_step_kind if planned.scope == root_scope else None,
            )
        if root_scope not in self._nodes:
            self._nodes[root_scope] = ComputeNodeRun(
                scope=root_scope,
                dependency_scopes=(),
                state="complete",
                priority_band=priority_band,
            )

    def _register_planned_node(
        self,
        planned: PlannedComputeNode,
        *,
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
        else:
            node.state = "waiting_deps"
            self._dequeue_ready(node.scope)

    def _failed_dependency_error(self, node: ComputeNodeRun) -> BaseException | None:
        for dependency_scope in node.dependency_scopes:
            dependency = self._nodes.get(dependency_scope)
            if dependency is not None and dependency.state == "failed":
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

    def _dequeue_ready(self, scope: ComputeScope) -> None:
        try:
            self._ready_queue.remove(scope)
        except ValueError:
            return

    def _dispatch(self) -> None:
        while self._ready_queue:
            scope, node = self._dequeue_dispatchable_ready_node()
            if scope is None or node is None:
                return

            registration = self._compute_registry[node.scope.analytic_id]
            step = self._current_step_spec(node, registration)
            if step.backend == "inline":
                self._begin_step_execution(node)
                self._run_inline(node, registration, step)
                continue

            if self._pool_submitter is None:
                self._enqueue_ready(scope)
                return
            self._begin_step_execution(node)
            self._submit_pool_step(node, registration, step)
            self._metrics.pool_submissions += 1
            return

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
            if not all(gate(node) for gate in self._dispatch_gates):
                self._ready_queue.append(scope)
                continue
            return scope, node
        return None, None

    def _submit_pool_step(
        self,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
        step: ComputeStepSpec,
    ) -> None:
        if self._pool_submitter is None:
            raise RuntimeError("pool_submitter is not configured")
        if step.backend in {"interpreter", "process"}:
            job_wire = self._build_job_wire(node, registration, step)
            run_step = registration.run_step[step.step_kind]
            self._pool_submitter(node, step, job_wire=job_wire, run_step=run_step)
            return
        self._pool_submitter(node, step)

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

    def _run_inline(
        self,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
        step: ComputeStepSpec,
    ) -> None:
        self._metrics.inline_executions += 1
        try:
            job_wire = self._build_job_wire(node, registration, step)
            result_wire = registration.run_step[step.step_kind](job_wire)
        except BaseException as exc:
            self._notify_step_complete(
                node,
                step.step_kind,
                surface="inline",
                terminal_state="failed",
            )
            self._fail_node(node, exc)
            return
        self._notify_step_complete(node, step.step_kind, surface="inline", terminal_state="success")
        self._after_step_success(node, result_wire)

    def _build_job_wire(
        self,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
        step: ComputeStepSpec,
    ) -> object:
        dependency_outputs = DependencyOutputs()
        for dependency_scope in node.dependency_scopes:
            dependency_node = self._nodes[dependency_scope]
            if dependency_node.result_wire is None:
                raise RuntimeError(
                    f"dependency {dependency_scope!r} is complete without a result wire"
                )
            dependency_outputs.put(dependency_scope, dependency_node.result_wire)
        builder = registration.build_step_job_wire[step.step_kind]
        return builder(
            node.scope,
            dependency_outputs=dependency_outputs,
            ctx=self._cached_ctx,
        )

    def _begin_step_execution(self, node: ComputeNodeRun) -> None:
        registration = self._compute_registry[node.scope.analytic_id]
        node.state = "running"
        node.generation_at_submit = registration.persistence_policy.invalidation_generation(
            self._ctx,
            node.scope,
        )

    def _current_invalidation_generation(self, node: ComputeNodeRun) -> int:
        registration = self._compute_registry[node.scope.analytic_id]
        return registration.persistence_policy.invalidation_generation(self._ctx, node.scope)

    def _is_epoch_stale(self, node: ComputeNodeRun) -> bool:
        if node.generation_at_submit is None:
            return False
        return self._current_invalidation_generation(node) != node.generation_at_submit

    def _retry_step_after_epoch_bump(self, node: ComputeNodeRun) -> None:
        self._metrics.epoch_discards += 1
        node.generation_at_submit = None
        node.state = "ready"
        self._enqueue_ready(node.scope)
        self._dispatch()

    def _after_step_success(self, node: ComputeNodeRun, result_wire: object | None) -> None:
        if self._is_epoch_stale(node):
            self._retry_step_after_epoch_bump(node)
            return

        step_result = coerce_step_result(result_wire)
        registration = self._compute_registry[node.scope.analytic_id]
        node.generation_at_submit = None

        if step_result.outcome == "continue":
            self._continue_node_step(node, registration)
            return

        if step_result.outcome == "persist":
            node.result_wire = step_result.payload
            post_lock_callback = registration.persistence_policy.persist(
                self._cached_ctx,
                node.scope,
                step_result.payload,
            )
            if post_lock_callback is not None:
                self._post_lock_callbacks.append(post_lock_callback)
            self._metrics.persist_calls += 1
            self._complete_node(node)
            return

        if step_result.outcome == "complete":
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
                node.profile_step_index = next_profile_index
        node.state = "ready"
        self._enqueue_ready(node.scope)
        self._dispatch()

    def _complete_node(self, node: ComputeNodeRun) -> None:
        node.state = "complete"
        self._dequeue_ready(node.scope)
        for waiter in node.waiters:
            waiter._waiter_error = None
        node.waiters.clear()
        self._notify_node_complete(node)
        self._post_lock_callbacks.append(
            lambda completed_scope=node.scope: self._handle_dependency_terminal(completed_scope),
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
        self._notify_node_complete(node)
        self._post_lock_callbacks.append(
            lambda completed_scope=node.scope: self._handle_dependency_terminal(completed_scope),
        )

    def _notify_node_complete(self, node: ComputeNodeRun) -> None:
        listeners = tuple(self._node_complete_listeners)
        for listener in listeners:
            self._post_lock_callbacks.append(
                lambda listener=listener, node=node: listener(node.scope, node),
            )

    def _notify_step_complete(
        self,
        node: ComputeNodeRun,
        step_kind: str,
        *,
        surface: Literal["inline", "pool"],
        terminal_state: Literal["success", "failed"],
    ) -> None:
        listeners = tuple(self._step_complete_listeners)
        for listener in listeners:
            self._post_lock_callbacks.append(
                lambda listener=listener, node=node, step_kind=step_kind: listener(
                    node.scope,
                    node,
                    step_kind,
                    surface,
                    terminal_state,
                ),
            )

    def _drain_post_lock_callbacks(self) -> None:
        while True:
            with self._condition:
                callbacks = tuple(self._post_lock_callbacks)
                self._post_lock_callbacks.clear()
            if not callbacks:
                return
            for callback in callbacks:
                callback()

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
        self._dispatch()

    def _has_pending_work(self) -> bool:
        return any(
            node.state in {"waiting_deps", "ready", "running"} for node in self._nodes.values()
        )
