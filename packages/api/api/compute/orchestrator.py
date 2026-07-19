"""Compute orchestrator DAG scheduler with singleflight and inline execution."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.orchestrator_lifecycle import OrchestratorLifecycleMixin
from api.compute.orchestrator_observers import OrchestratorObservers
from api.compute.orchestrator_state import (
    ComputeHandle,
    ComputeNodeRun,
    ComputeRequest,
    NodeState,
)
from api.compute.orchestrator_step_execution import OrchestratorStepExecutionMixin
from api.compute.orchestrator_submission import OrchestratorSubmissionMixin
from api.compute.pools import ComputePriorityBand, ComputeWorkerPool, PoolSubmitter
from api.compute.registry import AnalyticComputeRegistration
from api.compute.scope import ComputeScope
from api.compute.turn_cache import OrchestratorTurnCache
from api.models.game import TurnInfo

# Re-exports for external callers; in-package compute code imports state types
# from ``orchestrator_state`` (the owning module).
__all__ = [
    "ComputeHandle",
    "ComputeNodeRun",
    "ComputeOrchestrator",
    "ComputeRequest",
    "NodeState",
    "OrchestratorDiagnosticsSnapshot",
    "OrchestratorMetrics",
    "OrchestratorNodeSnapshot",
]


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


class ComputeOrchestrator(
    OrchestratorStepExecutionMixin,
    OrchestratorLifecycleMixin,
    OrchestratorSubmissionMixin,
):
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

    Observer registration (dispatch gates, lifecycle listeners, etc.) lives on
    :attr:`observers` -- call ``orchestrator.observers.register_*`` directly.
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
        self._next_execution_generation = 1
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

    @property
    def observers(self) -> OrchestratorObservers:
        """Listener registration, notify fan-out, and post-lock callback drain."""
        return self._observers

    @property
    def nodes(self) -> Mapping[ComputeScope, ComputeNodeRun]:
        return self._nodes

    def ready_scopes(self) -> tuple[ComputeScope, ...]:
        """Return scopes currently in the ready queue."""
        with self._condition:
            return self._ready_scopes_snapshot()

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
            return OrchestratorDiagnosticsSnapshot(
                nodes=nodes,
                ready_scopes=self._ready_scopes_snapshot(),
            )

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
                    step_kind=step_kind,
                    step_index=step_index,
                    detail={
                        "reason": "missing_node",
                        "hadError": error is not None,
                    },
                )
            elif node.state != "running":
                # Already aborted/cancelled/replaced while the pool worker was finishing.
                # step_kind / step_index identify the finishing pool work item, which
                # may differ from the node's current (already-moved-on) step.
                self._observers.notify_lifecycle(
                    "pool_finish_ignored",
                    scope,
                    node=node,
                    step_kind=step_kind,
                    step_index=step_index,
                    detail={
                        "reason": "node_not_running",
                        "priorState": node.state,
                        "priorStepIndex": node.step_index,
                        "priorProfileStepIndex": node.profile_step_index,
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

    def abort_scope(
        self,
        scope: ComputeScope,
        error: BaseException,
        *,
        expected_execution_generation: int | None = None,
    ) -> bool:
        """Abort a non-terminal node so a later ``force_fresh`` submit can replace it.

        Returns whether a node was aborted. No-op when the scope is absent or already
        terminal, or when it is no longer the expected execution generation. Used when
        a stream row run is cancelled while orchestrator work for that scope is still
        in flight.

        Prefer :class:`ComputeScopeAbortedError` for intentional cancels: the node
        becomes ``failed`` for force_fresh replacement, but dependents do **not**
        cascade-fail (they stay ``waiting_deps`` on the singleton DAG).
        """
        with self._condition:
            node = self._nodes.get(scope)
            if node is None or node.is_terminal:
                return False
            if (
                expected_execution_generation is not None
                and node.execution_generation != expected_execution_generation
            ):
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
                step_kind=finished_step_kind,
                step_index=finished_step_index,
                detail={
                    "reason": "abort_scope",
                    "priorState": prior_state,
                    "priorProfileStepIndex": node.profile_step_index,
                    "wasRunning": was_running,
                    "errorType": type(error).__name__,
                },
            )
            self._fail_node(node, error)
        self._observers.drain_post_lock_callbacks()
        return True

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

    def execution_generation_for_scope(self, scope: ComputeScope) -> int | None:
        """Return the current execution identity for ``scope``."""
        with self._condition:
            node = self._nodes.get(scope)
            return None if node is None else node.execution_generation

    def _refresh_all_readiness(self) -> None:
        for node in self._nodes.values():
            if node.blocks_readiness_refresh:
                continue
            self._refresh_node_readiness(node)

    def _refresh_node_readiness(self, node: ComputeNodeRun) -> None:
        if node.blocks_readiness_refresh:
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

    def _ready_depth(self) -> int:
        return sum(1 for scope in self._ready_queue if self._nodes[scope].state == "ready")

    def _ready_scopes_snapshot(self) -> tuple[ComputeScope, ...]:
        """Return ready-queue scopes still in ``ready`` state (caller holds lock)."""
        return tuple(scope for scope in self._ready_queue if self._nodes[scope].state == "ready")

    def _notify_ready_queue_changed(self) -> None:
        """Push the current ready-scopes snapshot to depth listeners (caller holds lock)."""
        self._observers.notify_ready_queue_changed(self._ready_scopes_snapshot())

    def _handle_dependency_terminal(self, completed_scope: ComputeScope) -> None:
        with self._condition:
            self._on_dependency_terminal(completed_scope)

    def _on_dependency_terminal(self, completed_scope: ComputeScope) -> None:
        for node in self._nodes.values():
            if completed_scope not in node.dependency_scopes:
                continue
            if node.blocks_readiness_refresh:
                continue
            self._refresh_node_readiness(node)
        # Defer dispatch: this runs under the orchestrator lock via
        # ``_handle_dependency_terminal``, and pool submit must not nest here.
        self._observers.schedule_post_lock(self.dispatch_ready_work)

    def _has_pending_work(self) -> bool:
        # ``parked`` is idle until an explicit ``force_fresh`` wake -- not dispatchable.
        return any(
            node.state in {"waiting_deps", "ready", "running"} for node in self._nodes.values()
        )
