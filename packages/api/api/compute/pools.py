"""Global compute worker pool with priority bands and backend dispatch."""

from __future__ import annotations

import os
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, InterpreterPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from api.compute.profile import ComputeBackend, ComputeStepSpec
from api.compute.scope import ComputeScope
from api.compute.wire import RunStepFn

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator

ComputePriorityBand = Literal["stream_attached", "interactive_ensure", "background"]

PRIORITY_BAND_RANK: dict[ComputePriorityBand, int] = {
    "stream_attached": 0,
    "interactive_ensure": 1,
    "background": 2,
}

_DEFAULT_WORKER_COUNT = 4
_DEQUEUE_WAIT_SECONDS = 0.25


class PoolSubmitter(Protocol):
    """Callback the orchestrator uses to enqueue ready steps on a worker pool."""

    def __call__(
        self,
        node: ComputeNodeRun,
        step: ComputeStepSpec,
        *,
        job_wire: object | None = None,
        run_step: RunStepFn | None = None,
    ) -> None: ...


def configured_worker_count() -> int:
    raw = os.environ.get("COMPUTE_ORCHESTRATOR_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return _DEFAULT_WORKER_COUNT


@dataclass(frozen=True)
class PoolWorkItem:
    """One schedulable pool unit dequeued by priority band and fairness rules."""

    orchestrator_id: int
    scope: ComputeScope
    step_kind: str
    backend: ComputeBackend
    priority_band: ComputePriorityBand
    step_index: int
    job_wire: object | None = None
    run_step: RunStepFn | None = None


@dataclass
class PoolMetrics:
    """Counters for pool dequeue and backend dispatch."""

    dequeues: int = 0
    thread_executions: int = 0
    interpreter_executions: int = 0
    process_executions: int = 0


def dequeue_next_work_item(queue: deque[PoolWorkItem]) -> PoolWorkItem | None:
    """Dequeue the next work item using priority bands and within-band fairness.

    Within a band, initial steps (step_index == 0) run before continuations.
    Among continuations, FIFO queue order provides round-robin across scopes.
    """
    if not queue:
        return None
    best_rank = min(PRIORITY_BAND_RANK[item.priority_band] for item in queue)
    candidate_indices = [
        index
        for index, item in enumerate(queue)
        if PRIORITY_BAND_RANK[item.priority_band] == best_rank
    ]
    for index in candidate_indices:
        if queue[index].step_index == 0:
            return _pop_at(queue, index)
    return _pop_at(queue, candidate_indices[0])


def _pop_at(queue: deque[PoolWorkItem], index: int) -> PoolWorkItem:
    item = queue[index]
    del queue[index]
    return item


class ComputeWorkerPool:
    """Process-wide worker pool with priority dequeue and backend dispatch."""

    def __init__(
        self,
        *,
        worker_count: int | None = None,
    ) -> None:
        self._worker_count = worker_count if worker_count is not None else configured_worker_count()
        self._orchestrators: dict[int, ComputeOrchestrator] = {}
        self._next_orchestrator_id = 0
        self._work_queue: deque[PoolWorkItem] = deque()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._shutdown = False
        self._workers: list[threading.Thread] = []
        self._metrics = PoolMetrics()
        self._interpreter_executor: InterpreterPoolExecutor | None = None
        self._process_executor: ProcessPoolExecutor | None = None
        for _ in range(self._worker_count):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self._workers.append(thread)

    @property
    def metrics(self) -> PoolMetrics:
        return self._metrics

    @property
    def worker_count(self) -> int:
        return self._worker_count

    def register(self, orchestrator: ComputeOrchestrator) -> int:
        """Register an orchestrator for pool completion routing; return its registration id."""
        with self._condition:
            orchestrator_id = self._next_orchestrator_id
            self._next_orchestrator_id += 1
            self._orchestrators[orchestrator_id] = orchestrator
            return orchestrator_id

    def unregister(self, orchestrator_id: int) -> None:
        """Remove an orchestrator and drop any queued work for it."""
        with self._condition:
            self._orchestrators.pop(orchestrator_id, None)
            if self._work_queue:
                self._work_queue = deque(
                    item
                    for item in self._work_queue
                    if item.orchestrator_id != orchestrator_id
                )

    def submitter_for(self, orchestrator_id: int) -> PoolSubmitter:
        """Return a pool submitter callback bound to one orchestrator registration."""
        return self._make_submitter(orchestrator_id)

    def submit(
        self,
        orchestrator_id: int,
        node: ComputeNodeRun,
        step: ComputeStepSpec,
        *,
        priority_band: ComputePriorityBand,
        job_wire: object | None = None,
        run_step: RunStepFn | None = None,
    ) -> None:
        """Enqueue one ready orchestrator step for pool execution."""
        with self._condition:
            self._work_queue.append(
                PoolWorkItem(
                    orchestrator_id=orchestrator_id,
                    scope=node.scope,
                    step_kind=step.step_kind,
                    backend=step.backend,
                    priority_band=priority_band,
                    step_index=node.step_index,
                    job_wire=job_wire,
                    run_step=run_step,
                )
            )
            self._condition.notify()

    def shutdown(self, *, wait_for_interpreters: bool = False) -> None:
        with self._condition:
            self._shutdown = True
            self._condition.notify_all()
        for thread in self._workers:
            thread.join(timeout=1.0)
        self._shutdown_executors(wait=wait_for_interpreters)

    def _make_submitter(self, orchestrator_id: int) -> PoolSubmitter:
        def _submit_from_orchestrator(
            node: ComputeNodeRun,
            step: ComputeStepSpec,
            *,
            job_wire: object | None = None,
            run_step: RunStepFn | None = None,
        ) -> None:
            self.submit(
                orchestrator_id,
                node,
                step,
                priority_band=node.priority_band,
                job_wire=job_wire,
                run_step=run_step,
            )

        return _submit_from_orchestrator

    def _worker_loop(self) -> None:
        while True:
            item = self._take_next_item()
            if item is None:
                return
            self._execute_item(item)

    def _take_next_item(self) -> PoolWorkItem | None:
        with self._condition:
            while not self._shutdown:
                item = dequeue_next_work_item(self._work_queue)
                if item is not None:
                    self._metrics.dequeues += 1
                    return item
                self._condition.wait(timeout=_DEQUEUE_WAIT_SECONDS)
            return None

    def _record_backend_execution_locked(self, backend: ComputeBackend) -> None:
        if backend == "thread":
            self._metrics.thread_executions += 1
        elif backend == "interpreter":
            self._metrics.interpreter_executions += 1
        elif backend == "process":
            self._metrics.process_executions += 1

    def _lookup_orchestrator(self, orchestrator_id: int) -> ComputeOrchestrator | None:
        with self._condition:
            return self._orchestrators.get(orchestrator_id)

    def _execute_item(self, item: PoolWorkItem) -> None:
        orchestrator = self._lookup_orchestrator(item.orchestrator_id)
        if orchestrator is None:
            return
        if item.backend == "thread":
            with self._condition:
                self._record_backend_execution_locked(item.backend)
            self._complete_from_callable(
                item.orchestrator_id,
                item.scope,
                orchestrator.execute_pool_step,
            )
            return
        if item.backend in {"interpreter", "process"}:
            if item.job_wire is None or item.run_step is None:
                raise RuntimeError(
                    f"pool step {item.step_kind!r} with backend {item.backend!r} "
                    f"requires a pre-built job wire and run_step"
                )
            with self._condition:
                self._record_backend_execution_locked(item.backend)
                if item.backend == "interpreter":
                    executor = self._interpreter_executor_locked()
                else:
                    executor = self._process_executor_locked()
            future = executor.submit(item.run_step, item.job_wire)
            self._complete_from_future(item.orchestrator_id, item.scope, future)
            return
        raise RuntimeError(f"unsupported pool backend {item.backend!r}")

    def _interpreter_executor_locked(self) -> InterpreterPoolExecutor:
        if self._interpreter_executor is None:
            self._interpreter_executor = InterpreterPoolExecutor(max_workers=self._worker_count)
        return self._interpreter_executor

    def _process_executor_locked(self) -> ProcessPoolExecutor:
        if self._process_executor is None:
            self._process_executor = ProcessPoolExecutor(max_workers=self._worker_count)
        return self._process_executor

    def _shutdown_executors(self, *, wait: bool = False) -> None:
        with self._condition:
            if self._interpreter_executor is not None:
                self._interpreter_executor.shutdown(wait=wait, cancel_futures=wait)
                self._interpreter_executor = None
            if self._process_executor is not None:
                self._process_executor.shutdown(wait=wait, cancel_futures=wait)
                self._process_executor = None

    def _complete_from_callable(
        self,
        orchestrator_id: int,
        scope: ComputeScope,
        run_step: Callable[[ComputeScope], object],
    ) -> None:
        try:
            result_wire = run_step(scope)
        except BaseException as exc:
            self._complete_pool_step_if_registered(orchestrator_id, scope, error=exc)
            return
        self._complete_pool_step_if_registered(
            orchestrator_id,
            scope,
            result_wire=result_wire,
        )

    def _complete_from_future(
        self,
        orchestrator_id: int,
        scope: ComputeScope,
        future: Future[object],
    ) -> None:
        try:
            result_wire = future.result()
        except BaseException as exc:
            self._complete_pool_step_if_registered(orchestrator_id, scope, error=exc)
            return
        self._complete_pool_step_if_registered(
            orchestrator_id,
            scope,
            result_wire=result_wire,
        )

    def _complete_pool_step_if_registered(
        self,
        orchestrator_id: int,
        scope: ComputeScope,
        *,
        result_wire: object | None = None,
        error: BaseException | None = None,
    ) -> None:
        orchestrator = self._lookup_orchestrator(orchestrator_id)
        if orchestrator is None:
            return
        orchestrator.complete_pool_step(scope, result_wire=result_wire, error=error)


_global_worker_pool: ComputeWorkerPool | None = None
_global_worker_pool_lock = threading.Lock()


def get_compute_worker_pool() -> ComputeWorkerPool:
    global _global_worker_pool
    with _global_worker_pool_lock:
        if _global_worker_pool is None:
            _global_worker_pool = ComputeWorkerPool()
        return _global_worker_pool


def shutdown_compute_worker_pool_for_tests() -> None:
    """Tear down the process-wide pool singleton (tests only)."""
    global _global_worker_pool
    with _global_worker_pool_lock:
        if _global_worker_pool is not None:
            _global_worker_pool.shutdown(wait_for_interpreters=True)
            _global_worker_pool = None


def reset_compute_worker_pool_for_tests(*, worker_count: int = 0) -> ComputeWorkerPool:
    global _global_worker_pool
    with _global_worker_pool_lock:
        if _global_worker_pool is not None:
            _global_worker_pool.shutdown(wait_for_interpreters=True)
        _global_worker_pool = ComputeWorkerPool(worker_count=worker_count)
        return _global_worker_pool
