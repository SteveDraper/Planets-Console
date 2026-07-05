"""Compute orchestrator DAG scheduler with singleflight and inline execution."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from api.analytics.export_context import AnalyticQueryContext
from api.compute.dag import PlannedComputeNode, plan_compute_dag
from api.compute.profile import ComputeStepSpec
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs

NodeState = Literal[
    "waiting_deps",
    "ready",
    "running",
    "attach_inflight",
    "complete",
    "failed",
]

PoolSubmitter = Callable[["ComputeNodeRun", ComputeStepSpec], None]


@dataclass(frozen=True)
class ComputeRequest:
    """One orchestrator submission for a compute scope."""

    scope: ComputeScope
    step_kind: str | None = None


@dataclass
class ComputeHandle:
    """Caller-visible orchestrator handle for one submission."""

    scope: ComputeScope
    _node: ComputeNodeRun
    is_waiter: bool = False
    error: BaseException | None = None

    @property
    def state(self) -> NodeState:
        if self.is_waiter and self._node.state == "running":
            return "attach_inflight"
        if self.is_waiter and self._node.state == "complete":
            return "complete"
        if self.is_waiter and self._node.state == "failed":
            return "failed"
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
    step_index: int = 0
    result_wire: object | None = None
    error: BaseException | None = None
    waiters: list[ComputeHandle] = field(default_factory=list)


@dataclass
class OrchestratorMetrics:
    """Test and diagnostics counters for orchestrator dispatch."""

    inline_executions: int = 0
    pool_submissions: int = 0


class ComputeOrchestrator:
    """DAG scheduler with singleflight per normalized compute scope."""

    def __init__(
        self,
        ctx: AnalyticQueryContext,
        *,
        compute_registry: Mapping[str, AnalyticComputeRegistration],
        pool_submitter: PoolSubmitter | None = None,
    ) -> None:
        self._ctx = ctx
        self._compute_registry = compute_registry
        self._pool_submitter = pool_submitter
        self._nodes: dict[ComputeScope, ComputeNodeRun] = {}
        self._ready_queue: deque[ComputeScope] = deque()
        self._metrics = OrchestratorMetrics()

    @property
    def metrics(self) -> OrchestratorMetrics:
        return self._metrics

    @property
    def nodes(self) -> Mapping[ComputeScope, ComputeNodeRun]:
        return self._nodes

    def ready_scopes(self) -> tuple[ComputeScope, ...]:
        """Return scopes currently in the ready queue."""
        return tuple(scope for scope in self._ready_queue if self._nodes[scope].state == "ready")

    def submit(self, request: ComputeRequest) -> ComputeHandle:
        """Submit or attach to in-flight work for one compute scope."""
        scope = request.scope
        existing = self._nodes.get(scope)
        if existing is not None:
            return self._attach_to_existing(existing)

        self._plan_and_register(scope)
        for node in self._nodes.values():
            self._refresh_node_readiness(node)
        handle = ComputeHandle(scope=scope, _node=self._nodes[scope])
        self._dispatch()
        return handle

    def run_until_idle(self) -> None:
        """Drain ready inline work until no ready or running nodes remain."""
        while self._has_pending_work():
            self._refresh_all_readiness()
            self._dispatch()
            if any(node.state == "running" for node in self._nodes.values()):
                break

    def complete_pool_step(
        self,
        scope: ComputeScope,
        *,
        result_wire: object | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Mark a pool-submitted step complete (used by worker pool integration)."""
        node = self._nodes[scope]
        if node.state != "running":
            raise RuntimeError(f"cannot complete pool step for node in state {node.state!r}")
        if error is not None:
            self._fail_node(node, error)
            return
        self._after_step_success(node, result_wire)

    def _attach_to_existing(self, node: ComputeNodeRun) -> ComputeHandle:
        if node.state in {"complete", "failed"}:
            return ComputeHandle(scope=node.scope, _node=node)
        handle = ComputeHandle(scope=node.scope, _node=node, is_waiter=True)
        node.waiters.append(handle)
        return handle

    def _plan_and_register(self, root_scope: ComputeScope) -> None:
        export_scope = compute_scope_to_export_scope(root_scope)
        planned_nodes = plan_compute_dag(
            self._ctx,
            root_scope.analytic_id,
            export_scope,
            compute_registry=self._compute_registry,
        )
        for planned in planned_nodes:
            self._register_planned_node(planned)
        if root_scope not in self._nodes:
            self._nodes[root_scope] = ComputeNodeRun(
                scope=root_scope,
                dependency_scopes=(),
                state="complete",
            )

    def _register_planned_node(self, planned: PlannedComputeNode) -> None:
        if planned.scope in self._nodes:
            return
        node = ComputeNodeRun(
            scope=planned.scope,
            dependency_scopes=planned.dependency_scopes,
        )
        self._nodes[planned.scope] = node

    def _refresh_all_readiness(self) -> None:
        for node in self._nodes.values():
            if node.state in {"complete", "failed", "running"}:
                continue
            self._refresh_node_readiness(node)

    def _refresh_node_readiness(self, node: ComputeNodeRun) -> None:
        if node.state in {"complete", "failed", "running"}:
            return
        if self._deps_complete(node):
            if node.state != "ready":
                node.state = "ready"
                self._enqueue_ready(node.scope)
        else:
            node.state = "waiting_deps"
            self._dequeue_ready(node.scope)

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
            scope = self._ready_queue[0]
            node = self._nodes[scope]
            if node.state != "ready":
                self._ready_queue.popleft()
                continue
            if not self._deps_complete(node):
                node.state = "waiting_deps"
                self._ready_queue.popleft()
                continue

            registration = self._compute_registry[node.scope.analytic_id]
            step = self._current_step_spec(node, registration)
            if step.backend == "inline":
                self._ready_queue.popleft()
                node.state = "running"
                self._run_inline(node, registration, step)
                continue

            if self._pool_submitter is None:
                return
            self._ready_queue.popleft()
            node.state = "running"
            self._pool_submitter(node, step)
            self._metrics.pool_submissions += 1
            return

    def _current_step_spec(
        self,
        node: ComputeNodeRun,
        registration: AnalyticComputeRegistration,
    ) -> ComputeStepSpec:
        steps = registration.compute_profile.steps
        if node.step_index >= len(steps):
            raise RuntimeError(
                f"compute node {node.scope!r} has no step at index {node.step_index}"
            )
        return steps[node.step_index]

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
            self._fail_node(node, exc)
            return
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
            ctx=self._ctx,
        )

    def _after_step_success(self, node: ComputeNodeRun, result_wire: object | None) -> None:
        registration = self._compute_registry[node.scope.analytic_id]
        node.step_index += 1
        if node.step_index < len(registration.compute_profile.steps):
            node.state = "ready"
            self._enqueue_ready(node.scope)
            self._dispatch()
            return
        node.result_wire = result_wire
        self._complete_node(node)

    def _complete_node(self, node: ComputeNodeRun) -> None:
        node.state = "complete"
        self._dequeue_ready(node.scope)
        for waiter in node.waiters:
            waiter.error = None
        node.waiters.clear()
        self._on_dependency_terminal(node.scope)

    def _fail_node(self, node: ComputeNodeRun, error: BaseException) -> None:
        node.state = "failed"
        node.error = error
        self._dequeue_ready(node.scope)
        for waiter in node.waiters:
            waiter.error = error
        node.waiters.clear()

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
