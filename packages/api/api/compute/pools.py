"""Global compute worker pool: band-ordered picks and backend dispatch.

A queued step carries no band. When a worker picks, each candidate ranks by
the band its orchestrator currently publishes for its scope, read without the
orchestrator lock. The band a step was picked at is fixed from then on.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import Future, InterpreterPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from api.compute.backend_runtime import effective_compute_backend, process_is_frozen
from api.compute.priority_band import PRIORITY_BAND_RANK, ComputePriorityBand
from api.compute.profile import ComputeBackend, ComputeStepSpec
from api.compute.remote_futures import RemotePoolFutureRecord, remote_future_record
from api.compute.scope import ComputeScope
from api.compute.wire import RunStepFn
from api.compute.worker_turn_cache import init_worker_turn_cache, worker_deserialize_calls

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator
    from api.compute.orchestrator_state import ComputeNodeRun

# Wider than historical 4: scores ``tier_solve`` is single-threaded CP-SAT, so
# parallelism is across per-player DAG nodes on this pool (not inside one Solve).
_DEFAULT_WORKER_COUNT = 8
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
    """One schedulable pool unit. Its band is read from its orchestrator at each pick."""

    orchestrator_id: int
    scope: ComputeScope
    step_kind: str
    backend: ComputeBackend
    step_index: int
    job_wire: object | None = None
    run_step: RunStepFn | None = None


@dataclass(frozen=True)
class BandedWorkItem:
    """A pool work item with the band its orchestrator published for it at one read.

    For a queued item the band is the one it would be picked at now. For a
    picked item it is the band it was picked at, which never changes after
    the pick.
    """

    item: PoolWorkItem
    priority_band: ComputePriorityBand


@dataclass
class PoolMetrics:
    """Counters for pool dequeue and backend dispatch."""

    dequeues: int = 0
    thread_executions: int = 0
    interpreter_executions: int = 0
    process_executions: int = 0


def work_pick_key(priority_band: ComputePriorityBand, step_index: int) -> tuple[int, int]:
    """Return the pick order key: higher band first, then initial steps before continuations."""
    return (PRIORITY_BAND_RANK[priority_band], 0 if step_index == 0 else 1)


def pick_next_work_item(candidates: Iterable[BandedWorkItem]) -> BandedWorkItem | None:
    """Return the candidate a worker picks next, or None when there is none.

    Ties keep candidate order, so queue (FIFO) order round-robins continuations
    across scopes within a band.
    """
    return min(
        candidates,
        key=lambda candidate: work_pick_key(candidate.priority_band, candidate.item.step_index),
        default=None,
    )


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
        self._on_item_dequeued: Callable[[BandedWorkItem, int], None] | None = None
        self._on_item_enqueued: Callable[[BandedWorkItem, int], None] | None = None
        self._on_item_finished: Callable[[PoolWorkItem], None] | None = None
        self._interpreter_executor: InterpreterPoolExecutor | None = None
        self._process_executor: ProcessPoolExecutor | None = None
        self._logged_backend_remaps: set[tuple[str, str]] = set()
        # Futures retained from executor.submit until done-callback finishes so
        # diagnostics can distinguish pending/running/done orphaned in-flight rows.
        # Dedicated lock: never nest with the diagnostics controller lock. Done
        # callbacks take controller via on_item_finished then unregister here;
        # pool workers take the pool condition then controller in on_item_dequeued.
        # Sharing the pool condition for unregister deadlocks (pool→controller vs
        # controller→pool).
        self._remote_futures_lock = threading.Lock()
        self._remote_futures: list[RemotePoolFutureRecord] = []
        self._worker_exception_count = 0
        self._last_dequeue_monotonic: float | None = None
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
        callback: Callable[[BandedWorkItem, int], None] | None,
    ) -> None:
        """Set a hook invoked once under the pool lock for the item actually dequeued.

        The first argument carries the band the item was picked at. The second
        is the work-queue depth after the item was popped.
        """
        with self._condition:
            self._on_item_dequeued = callback

    def set_on_item_enqueued(
        self,
        callback: Callable[[BandedWorkItem, int], None] | None,
    ) -> None:
        """Set a hook invoked after an item is enqueued (outside the pool lock).

        The first argument carries the band published for the item at enqueue.
        The second is the work-queue depth after the append. Invoked
        outside the pool condition so the callback may take the diagnostics
        controller lock without nesting under the pool lock (workers hold pool
        then controller in predicate / on_dequeued).
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

    def snapshot_work_queue(self) -> tuple[BandedWorkItem, ...]:
        """Return queued items in queue order with the band each would be picked at now."""
        with self._condition:
            return tuple(self._with_published_band_locked(item) for item in self._work_queue)

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

    def worker_health(self) -> dict[str, object]:
        """Return alive-thread / exception counters for compute diagnostics."""
        with self._condition:
            alive = sum(1 for thread in self._workers if thread.is_alive())
            exceptions = self._worker_exception_count
            last_dequeue = self._last_dequeue_monotonic
        return {
            "configuredWorkers": self._worker_count,
            "aliveWorkers": alive,
            "workerExceptionCount": exceptions,
            "lastDequeueMonotonic": last_dequeue,
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

    def take_next_item_for_tests(self) -> BandedWorkItem | None:
        """Dequeue one item using live predicate / on_dequeued hooks (tests only)."""
        with self._condition:
            return self._pop_runnable_item_locked()

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
        job_wire: object | None = None,
        run_step: RunStepFn | None = None,
    ) -> None:
        """Enqueue one ready orchestrator step for pool execution."""
        item = PoolWorkItem(
            orchestrator_id=orchestrator_id,
            scope=node.scope,
            step_kind=step.step_kind,
            backend=step.backend,
            step_index=node.step_index,
            job_wire=job_wire,
            run_step=run_step,
        )
        with self._condition:
            self._work_queue.append(item)
            on_enqueued = self._on_item_enqueued
            enqueued = self._with_published_band_locked(item)
            queue_depth = len(self._work_queue)
            self._condition.notify()
        # Outside the pool lock: enqueue hooks take the diagnostics controller lock
        # (must not nest under the pool condition -- workers hold pool then
        # controller in predicate / on_dequeued).
        if on_enqueued is not None:
            on_enqueued(enqueued, queue_depth)

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
                job_wire=job_wire,
                run_step=run_step,
            )

        return _submit_from_orchestrator

    def _worker_loop(self) -> None:
        while True:
            try:
                picked = self._take_next_item()
            except BaseException:
                with self._condition:
                    self._worker_exception_count += 1
                logger.exception("compute pool worker failed while dequeuing; continuing")
                continue
            if picked is None:
                return
            try:
                self._execute_item(picked)
            except BaseException:
                with self._condition:
                    self._worker_exception_count += 1
                logger.exception(
                    "compute pool worker failed while executing %s %s; continuing",
                    picked.item.step_kind,
                    picked.item.scope,
                )

    def _take_next_item(self) -> BandedWorkItem | None:
        with self._condition:
            while not self._shutdown:
                picked = self._pop_runnable_item_locked()
                if picked is not None:
                    return picked
                self._condition.wait(timeout=_DEQUEUE_WAIT_SECONDS)
            return None

    def _pop_runnable_item_locked(self) -> BandedWorkItem | None:
        """Pick, pop, and record one runnable item at its currently published band.

        The dequeue predicate is evaluated for every queued item before the pick.
        It must be side-effect free: grant or other mutable gate state belongs in
        the ``on_item_dequeued`` hook, invoked here after the pop so concurrent
        workers cannot both claim the same grant.
        """
        predicate = self._dequeue_predicate
        on_dequeued = self._on_item_dequeued
        picked = pick_next_work_item(
            [
                self._with_published_band_locked(item)
                for item in self._work_queue
                if predicate is None or predicate(item)
            ]
        )
        if picked is None:
            return None
        picked_index = next(
            index for index, queued in enumerate(self._work_queue) if queued is picked.item
        )
        del self._work_queue[picked_index]
        self._metrics.dequeues += 1
        self._last_dequeue_monotonic = time.monotonic()
        # Same critical section as pop -- grant burn must be atomic with selection.
        # Callback may take the diagnostics controller lock (pool -> controller).
        if on_dequeued is not None:
            on_dequeued(picked, len(self._work_queue))
        return picked

    def _with_published_band_locked(self, item: PoolWorkItem) -> BandedWorkItem:
        """Pair ``item`` with the band its orchestrator publishes for its scope.

        Reads the orchestrator's immutable band map and never takes the
        orchestrator lock. An item whose orchestrator is gone, or whose scope
        has no published band, ranks as ``background``.
        """
        orchestrator = self._orchestrators.get(item.orchestrator_id)
        band = None if orchestrator is None else orchestrator.published_band(item.scope)
        return BandedWorkItem(item=item, priority_band="background" if band is None else band)

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

    def _execute_item(self, picked: BandedWorkItem) -> None:
        """Run one dequeued item.

        Thread-backend work runs synchronously on the pool worker. Interpreter and
        process backends submit to their executors and complete via done callbacks
        so a stuck remote future cannot pin a pool worker thread (and stall the
        rest of the queue under freeze single-step).

        Frozen processes and ``api.remap_interpreter_backend_to_thread`` remap
        ``interpreter`` to ``thread`` before dispatch: PyInstaller
        subinterpreters cannot import application modules.
        """
        item = picked.item
        orchestrator = self._lookup_orchestrator(item.orchestrator_id)
        if orchestrator is None:
            self._notify_item_finished(item)
            return
        backend = effective_compute_backend(item.backend)
        if backend != item.backend:
            self._log_backend_remap(item.backend, backend)
        if backend == "thread":
            try:
                with self._condition:
                    self._record_backend_execution_locked(backend)
                self._complete_from_callable(
                    item.orchestrator_id,
                    item.scope,
                    orchestrator.execute_pool_step,
                    step_kind=item.step_kind,
                    step_index=item.step_index,
                )
            finally:
                self._notify_item_finished(item)
            return
        if backend in {"interpreter", "process"}:
            if item.job_wire is None or item.run_step is None:
                self._notify_item_finished(item)
                raise RuntimeError(
                    f"pool step {item.step_kind!r} with backend {item.backend!r} "
                    f"requires a pre-built job wire and run_step"
                )
            with self._condition:
                self._record_backend_execution_locked(backend)
                if backend == "interpreter":
                    executor = self._interpreter_executor_locked()
                else:
                    executor = self._process_executor_locked()
            future = executor.submit(item.run_step, item.job_wire)
            self._register_remote_future(picked, future)
            future.add_done_callback(
                lambda completed, pool_item=item: self._on_remote_future_done(
                    pool_item,
                    completed,
                )
            )
            return
        self._notify_item_finished(item)
        raise RuntimeError(f"unsupported pool backend {backend!r}")

    def _log_backend_remap(
        self,
        declared: ComputeBackend,
        effective: ComputeBackend,
    ) -> None:
        key = (declared, effective)
        with self._condition:
            if key in self._logged_backend_remaps:
                return
            self._logged_backend_remaps.add(key)
        if process_is_frozen():
            reason = (
                "frozen process; InterpreterPoolExecutor cannot import "
                "application modules under PyInstaller"
            )
        else:
            reason = "api.remap_interpreter_backend_to_thread"
        logger.info("Compute backend %r remapped to %r (%s)", declared, effective, reason)

    def _register_remote_future(self, picked: BandedWorkItem, future: Future[object]) -> None:
        item = picked.item
        record = remote_future_record(
            orchestrator_id=item.orchestrator_id,
            scope=item.scope,
            step_kind=item.step_kind,
            step_index=item.step_index,
            priority_band=picked.priority_band,
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
            self._condition.notify_all()
        if on_finished is not None:
            on_finished(item)

    def _on_remote_future_done(self, item: PoolWorkItem, future: Future[object]) -> None:
        try:
            self._complete_from_future(
                item.orchestrator_id,
                item.scope,
                future,
                step_kind=item.step_kind,
                step_index=item.step_index,
            )
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
        *,
        step_kind: str | None = None,
        step_index: int | None = None,
    ) -> None:
        try:
            result_wire = run_step(scope)
        except BaseException as exc:
            self._complete_pool_step_if_registered(
                orchestrator_id,
                scope,
                error=exc,
                step_kind=step_kind,
                step_index=step_index,
            )
            return
        self._complete_pool_step_if_registered(
            orchestrator_id,
            scope,
            result_wire=result_wire,
            step_kind=step_kind,
            step_index=step_index,
        )

    def _complete_from_future(
        self,
        orchestrator_id: int,
        scope: ComputeScope,
        future: Future[object],
        *,
        step_kind: str | None = None,
        step_index: int | None = None,
    ) -> None:
        try:
            result_wire = future.result()
        except BaseException as exc:
            self._complete_pool_step_if_registered(
                orchestrator_id,
                scope,
                error=exc,
                step_kind=step_kind,
                step_index=step_index,
            )
            return
        self._complete_pool_step_if_registered(
            orchestrator_id,
            scope,
            result_wire=result_wire,
            step_kind=step_kind,
            step_index=step_index,
        )

    def _complete_pool_step_if_registered(
        self,
        orchestrator_id: int,
        scope: ComputeScope,
        *,
        result_wire: object | None = None,
        error: BaseException | None = None,
        step_kind: str | None = None,
        step_index: int | None = None,
    ) -> None:
        orchestrator = self._lookup_orchestrator(orchestrator_id)
        if orchestrator is None:
            return
        orchestrator.complete_pool_step(
            scope,
            result_wire=result_wire,
            error=error,
            step_kind=step_kind,
            step_index=step_index,
        )


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
