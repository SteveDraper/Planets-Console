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
from api.compute.remote_futures import RemotePoolFutureRecord, remote_future_record
from api.compute.scope import ComputeScope
from api.compute.wire import RunStepFn
from api.compute.worker_turn_cache import init_worker_turn_cache, worker_deserialize_calls

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


def dequeue_next_work_item(
    queue: deque[PoolWorkItem],
    *,
    predicate: Callable[[PoolWorkItem], bool] | None = None,
) -> PoolWorkItem | None:
    """Dequeue the next work item using priority bands and within-band fairness.

    Within a band, initial steps (step_index == 0) run before continuations.
    Among continuations, FIFO queue order provides round-robin across scopes.

    ``predicate`` is evaluated for every queued item before selection. It must be
    side-effect free -- grant or other mutable gate state belongs in an
    ``on_item_dequeued`` hook invoked under the pool lock after the chosen item
    is popped, so concurrent workers cannot both claim the same grant.
    """
    if not queue:
        return None
    allowed = [item for item in queue if predicate is None or predicate(item)]
    if not allowed:
        return None
    best_rank = min(PRIORITY_BAND_RANK[item.priority_band] for item in allowed)
    candidate_indices = [
        index
        for index, item in enumerate(queue)
        if item in allowed and PRIORITY_BAND_RANK[item.priority_band] == best_rank
    ]
    for index in candidate_indices:
        if queue[index].step_index == 0:
            return _pop_at(queue, index)
    return _pop_at(queue, candidate_indices[0])


def _pop_at(queue: deque[PoolWorkItem], index: int) -> PoolWorkItem:
    item = queue[index]
    del queue[index]
    return item


def _executor_queue_depth(executor: object | None) -> int | None:
    """Best-effort pending-work depth for Thread/Interpreter/Process pool executors."""
    if executor is None:
        return None
    work_queue = getattr(executor, "_work_queue", None)
    if work_queue is None:
        return None
    qsize = getattr(work_queue, "qsize", None)
    if not callable(qsize):
        return None
    try:
        return int(qsize())
    except Exception:
        return None


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
        self._dequeue_predicate: Callable[[PoolWorkItem], bool] | None = None
        self._on_item_dequeued: Callable[[PoolWorkItem, int], None] | None = None
        self._on_item_enqueued: Callable[[PoolWorkItem, int], None] | None = None
        self._on_item_finished: Callable[[PoolWorkItem], None] | None = None
        self._interpreter_executor: InterpreterPoolExecutor | None = None
        self._process_executor: ProcessPoolExecutor | None = None
        # Futures retained from executor.submit until done-callback finishes so
        # diagnostics can distinguish pending/running/done orphaned in-flight rows.
        # Dedicated lock: never nest with the diagnostics controller lock. Done
        # callbacks take controller via on_item_finished then unregister here;
        # pool workers take the pool condition then controller in on_item_dequeued.
        # Sharing the pool condition for unregister deadlocks (pool→controller vs
        # controller→pool).
        self._remote_futures_lock = threading.Lock()
        self._remote_futures: list[RemotePoolFutureRecord] = []
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

    def set_dequeue_predicate(
        self,
        predicate: Callable[[PoolWorkItem], bool] | None,
    ) -> None:
        """Set a side-effect-free predicate that must return True for dequeue eligibility."""
        with self._condition:
            self._dequeue_predicate = predicate

    def set_on_item_dequeued(
        self,
        callback: Callable[[PoolWorkItem, int], None] | None,
    ) -> None:
        """Set a hook invoked once under the pool lock for the item actually dequeued.

        The second argument is the work-queue depth after the item was popped.
        """
        with self._condition:
            self._on_item_dequeued = callback

    def set_on_item_enqueued(
        self,
        callback: Callable[[PoolWorkItem, int], None] | None,
    ) -> None:
        """Set a hook invoked under the pool lock after an item is enqueued.

        The second argument is the work-queue depth after the append.
        """
        with self._condition:
            self._on_item_enqueued = callback

    def set_on_item_finished(
        self,
        callback: Callable[[PoolWorkItem], None] | None,
    ) -> None:
        """Set a hook invoked after a dequeued item finishes (success, error, or abandon).

        Called outside the pool lock so the callback may take other locks (e.g.
        diagnostics controller) without nesting under the pool condition.
        """
        with self._condition:
            self._on_item_finished = callback

    def snapshot_work_queue(self) -> tuple[PoolWorkItem, ...]:
        with self._condition:
            return tuple(self._work_queue)

    def snapshot_remote_futures(self) -> tuple[RemotePoolFutureRecord, ...]:
        """Return interpreter/process futures still tracked between submit and finish."""
        with self._remote_futures_lock:
            return tuple(self._remote_futures)

    def remote_executor_probe(self) -> dict[str, object]:
        """Best-effort executor sizing / queue depth for diagnostics (may be None)."""
        with self._condition:
            interpreter = self._interpreter_executor
            process = self._process_executor
            worker_count = self._worker_count
        return {
            "interpreterMaxWorkers": worker_count if interpreter is not None else None,
            "processMaxWorkers": worker_count if process is not None else None,
            "interpreterQueueDepth": _executor_queue_depth(interpreter),
            "processQueueDepth": _executor_queue_depth(process),
        }

    def wake_workers(self) -> bool:
        """Wake pool workers waiting on an empty or fully-held queue."""
        with self._condition:
            had_waiters = bool(self._work_queue)
            self._condition.notify_all()
            return had_waiters

    def enqueue_for_tests(self, item: PoolWorkItem) -> None:
        """Enqueue one work item without going through orchestrator dispatch (tests only)."""
        with self._condition:
            self._work_queue.append(item)
            self._condition.notify()

    def take_next_item_for_tests(self) -> PoolWorkItem | None:
        """Dequeue one item using live predicate / on_dequeued hooks (tests only)."""
        with self._condition:
            on_dequeued = self._on_item_dequeued
            item = dequeue_next_work_item(self._work_queue, predicate=self._dequeue_predicate)
            if item is None:
                return None
            self._metrics.dequeues += 1
            # Same critical section as pop -- grant burn must be atomic with selection.
            if on_dequeued is not None:
                on_dequeued(item, len(self._work_queue))
            return item

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
                    item for item in self._work_queue if item.orchestrator_id != orchestrator_id
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
            item = PoolWorkItem(
                orchestrator_id=orchestrator_id,
                scope=node.scope,
                step_kind=step.step_kind,
                backend=step.backend,
                priority_band=priority_band,
                step_index=node.step_index,
                job_wire=job_wire,
                run_step=run_step,
            )
            self._work_queue.append(item)
            on_enqueued = self._on_item_enqueued
            queue_depth = len(self._work_queue)
            if on_enqueued is not None:
                on_enqueued(item, queue_depth)
            self._condition.notify()

    def shutdown(self, *, wait_for_interpreters: bool = False) -> None:
        with self._condition:
            self._shutdown = True
            self._condition.notify_all()
        for thread in self._workers:
            thread.join(timeout=1.0)
        self._shutdown_executors(wait=wait_for_interpreters)

    def worker_deserialize_calls_for_tests(self) -> int:
        """Return turn-wire deserialize count from an interpreter pool worker (tests only)."""
        with self._condition:
            executor = self._interpreter_executor
            if executor is None:
                return 0
        return executor.submit(worker_deserialize_calls).result()

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
                predicate = self._dequeue_predicate
                on_dequeued = self._on_item_dequeued
                item = dequeue_next_work_item(self._work_queue, predicate=predicate)
                if item is not None:
                    self._metrics.dequeues += 1
                    # Same critical section as pop -- grant burn must be atomic with selection.
                    # Callback may take the diagnostics controller lock (pool -> controller).
                    if on_dequeued is not None:
                        on_dequeued(item, len(self._work_queue))
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
        """Run one dequeued item.

        Thread-backend work runs synchronously on the pool worker. Interpreter and
        process backends submit to their executors and complete via done callbacks
        so a stuck remote future cannot pin a pool worker thread (and stall the
        rest of the queue under freeze single-step).
        """
        orchestrator = self._lookup_orchestrator(item.orchestrator_id)
        if orchestrator is None:
            self._notify_item_finished(item)
            return
        if item.backend == "thread":
            try:
                with self._condition:
                    self._record_backend_execution_locked(item.backend)
                self._complete_from_callable(
                    item.orchestrator_id,
                    item.scope,
                    orchestrator.execute_pool_step,
                )
            finally:
                self._notify_item_finished(item)
            return
        if item.backend in {"interpreter", "process"}:
            if item.job_wire is None or item.run_step is None:
                self._notify_item_finished(item)
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
            self._register_remote_future(item, future)
            future.add_done_callback(
                lambda completed, pool_item=item: self._on_remote_future_done(
                    pool_item,
                    completed,
                )
            )
            return
        self._notify_item_finished(item)
        raise RuntimeError(f"unsupported pool backend {item.backend!r}")

    def _register_remote_future(self, item: PoolWorkItem, future: Future[object]) -> None:
        record = remote_future_record(
            orchestrator_id=item.orchestrator_id,
            scope=item.scope,
            step_kind=item.step_kind,
            step_index=item.step_index,
            priority_band=item.priority_band,
            backend=item.backend,
            future=future,
        )
        with self._remote_futures_lock:
            self._remote_futures.append(record)

    def _unregister_remote_future(self, future: Future[object]) -> None:
        with self._remote_futures_lock:
            self._remote_futures = [
                record for record in self._remote_futures if record.future is not future
            ]

    def _notify_item_finished(self, item: PoolWorkItem) -> None:
        with self._condition:
            on_finished = self._on_item_finished
        if on_finished is not None:
            on_finished(item)

    def _on_remote_future_done(self, item: PoolWorkItem, future: Future[object]) -> None:
        try:
            self._complete_from_future(item.orchestrator_id, item.scope, future)
        finally:
            # Unregister after complete/persist so a mid-callback snapshot can still
            # observe futureState=done while the DAG node remains running.
            # Use ``_remote_futures_lock`` only -- never the pool condition -- so this
            # cannot ABBA-deadlock with workers that hold the pool condition while
            # calling on_item_dequeued (controller lock).
            try:
                self._notify_item_finished(item)
            finally:
                self._unregister_remote_future(future)

    def _interpreter_executor_locked(self) -> InterpreterPoolExecutor:
        if self._interpreter_executor is None:
            self._interpreter_executor = InterpreterPoolExecutor(
                max_workers=self._worker_count,
                initializer=init_worker_turn_cache,
            )
        return self._interpreter_executor

    def _process_executor_locked(self) -> ProcessPoolExecutor:
        if self._process_executor is None:
            self._process_executor = ProcessPoolExecutor(
                max_workers=self._worker_count,
                initializer=init_worker_turn_cache,
            )
        return self._process_executor

    def _shutdown_executors(self, *, wait: bool = False) -> None:
        # Drop executor refs under the pool lock, then shut down outside it.
        # Interpreter/process done-callbacks take ``self._condition`` (via
        # ``_notify_item_finished``); waiting on ``shutdown(wait=True)`` while
        # holding that lock deadlocks when in-flight remote work completes.
        with self._condition:
            interpreter = self._interpreter_executor
            process = self._process_executor
            self._interpreter_executor = None
            self._process_executor = None
        if interpreter is not None:
            interpreter.shutdown(wait=wait, cancel_futures=wait)
        if process is not None:
            process.shutdown(wait=wait, cancel_futures=wait)

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
        pool = _global_worker_pool
        _global_worker_pool = None
    # Shut down outside the singleton lock: completion callbacks may re-enter
    # ``get_compute_worker_pool`` / pool internals while ``wait=True``.
    if pool is not None:
        pool.shutdown(wait_for_interpreters=True)


def reset_compute_worker_pool_for_tests(*, worker_count: int = 0) -> ComputeWorkerPool:
    global _global_worker_pool
    with _global_worker_pool_lock:
        previous = _global_worker_pool
        _global_worker_pool = None
    if previous is not None:
        previous.shutdown(wait_for_interpreters=True)
    with _global_worker_pool_lock:
        _global_worker_pool = ComputeWorkerPool(worker_count=worker_count)
        return _global_worker_pool
