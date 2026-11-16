"""A remote pool step whose executor cannot take it.

When getting the executor or submitting to it raises, the error is reported
to the orchestrator as the step's error, so the node leaves ``running``. An
executor that is broken or shut down is dropped and shut down outside the pool
condition, so the next step on that backend starts a new executor.
"""

from __future__ import annotations

import time
from concurrent.futures import BrokenExecutor
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import MagicMock

import pytest
from api.compute import ComputeOrchestrator, ComputeRequest, ComputeScope, build_compute_registry
from api.compute.pools import BandedWorkItem, ComputeWorkerPool, PoolWorkItem, RemoteStepWork
from api.compute.profile import REMOTE_COMPUTE_BACKENDS, RemoteComputeBackend
from api.compute.wire import StepResult

from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_pools import (
    _FLEET_ANALYTIC_ID,
    _POOL_EXPORT_REGISTRY,
    _process_backend_registration,
    _scope_for_player,
)


class _RefusingExecutor:
    """An executor whose ``submit`` raises ``error``; records each shutdown and its lock state."""

    def __init__(self, pool: ComputeWorkerPool, error: BaseException) -> None:
        self._pool = pool
        self._error = error
        self.shutdowns: list[tuple[bool, bool]] = []

    def submit(self, *_args: object, **_kwargs: object) -> object:
        raise self._error

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        del cancel_futures
        is_condition_free = self._pool._lock.acquire(blocking=False)
        if is_condition_free:
            self._pool._lock.release()
        self.shutdowns.append((wait, is_condition_free))


def _seed_executor(
    pool: ComputeWorkerPool, backend: RemoteComputeBackend, executor: object
) -> None:
    with pool._condition:
        if backend == "interpreter":
            pool._interpreter_executor = executor  # type: ignore[assignment]
        else:
            pool._process_executor = executor  # type: ignore[assignment]


def _cached_executor(pool: ComputeWorkerPool, backend: RemoteComputeBackend) -> object | None:
    with pool._condition:
        return pool._cached_remote_executor_locked(backend)


def _remote_item(orchestrator_id: int, backend: RemoteComputeBackend) -> PoolWorkItem:
    return PoolWorkItem(
        orchestrator_id=orchestrator_id,
        scope=ComputeScope(
            analytic_id="fleet", game_id=628580, perspective=11, turn=5, player_id=3
        ),
        execution_generation=0,
        step_kind="materialization_leg",
        backend=backend,
        step_index=0,
        work=RemoteStepWork(
            backend=backend,
            job_wire={},
            run_step=lambda _job: StepResult(outcome="complete"),
        ),
    )


@pytest.mark.parametrize("backend", REMOTE_COMPUTE_BACKENDS)
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(BrokenExecutor("a worker died"), id="broken"),
        pytest.param(RuntimeError("cannot schedule new futures after shutdown"), id="shut-down"),
    ],
)
def test_submit_refused_by_an_unusable_executor_reports_the_error_and_drops_it(backend, error):
    pool = ComputeWorkerPool(worker_count=0)
    try:
        orchestrator = MagicMock()
        orchestrator_id = pool.register(orchestrator)
        finished: list[PoolWorkItem] = []
        pool.set_on_item_finished(finished.append)
        executor = _RefusingExecutor(pool, error)
        _seed_executor(pool, backend, executor)
        item = _remote_item(orchestrator_id, backend)

        pool._execute_item(BandedWorkItem(item=item, priority_band="background"))

        orchestrator.complete_pool_step.assert_called_once_with(
            item.scope,
            item.execution_generation,
            result_wire=None,
            error=error,
            step_kind=item.step_kind,
            step_index=item.step_index,
        )
        assert finished == [item]
        assert pool.snapshot_remote_futures() == ()
        assert _cached_executor(pool, backend) is None
        assert executor.shutdowns == [(False, True)]
    finally:
        pool.shutdown()


def test_submit_error_that_does_not_mean_an_unusable_executor_keeps_it():
    """A per-step failure at submit (e.g. an unpicklable job) fails the step only."""
    pool = ComputeWorkerPool(worker_count=0)
    try:
        orchestrator = MagicMock()
        orchestrator_id = pool.register(orchestrator)
        error = TypeError("cannot pickle the job wire")
        executor = _RefusingExecutor(pool, error)
        _seed_executor(pool, "interpreter", executor)

        pool._execute_item(
            BandedWorkItem(
                item=_remote_item(orchestrator_id, "interpreter"), priority_band="background"
            )
        )

        assert orchestrator.complete_pool_step.call_args.kwargs["error"] is error
        assert _cached_executor(pool, "interpreter") is executor
        assert executor.shutdowns == []
    finally:
        pool.shutdown()


def test_a_replaced_executor_is_not_dropped_by_a_late_refusal():
    pool = ComputeWorkerPool(worker_count=0)
    try:
        refused = _RefusingExecutor(pool, BrokenExecutor("a worker died"))
        replacement = MagicMock()
        _seed_executor(pool, "process", replacement)

        pool._discard_remote_executor("process", refused)  # type: ignore[arg-type]

        assert _cached_executor(pool, "process") is replacement
        assert refused.shutdowns == []
        replacement.shutdown.assert_not_called()
    finally:
        _seed_executor(pool, "process", None)
        pool.shutdown()


def _wait_terminal(handle, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and handle.state not in ("complete", "failed"):
        time.sleep(0.01)


def test_broken_process_executor_fails_its_step_and_the_next_step_runs_on_a_new_one(
    sample_turn,
):
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_process_backend_registration(),)),
        worker_pool=pool,
    )
    player_ids = [row.ownerid for row in sample_turn.scores][:2]
    broken_scope, next_scope = (
        ComputeScope(
            analytic_id=_FLEET_ANALYTIC_ID,
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn=scope.turn,
            player_id=scope.player_id,
        )
        for scope in (_scope_for_player(sample_turn, player_id) for player_id in player_ids)
    )
    broken = _RefusingExecutor(pool, BrokenProcessPool("a worker died"))
    _seed_executor(pool, "process", broken)
    try:
        broken_handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=broken_scope))
        _wait_terminal(broken_handle)

        assert broken_handle.state == "failed"
        assert isinstance(broken_handle.error, BrokenProcessPool)
        assert broken.shutdowns == [(False, True)]

        next_handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=next_scope))
        _wait_terminal(next_handle)

        assert next_handle.state == "complete", next_handle.error
        assert next_handle.result_wire == {"result": _FLEET_ANALYTIC_ID}
        assert _cached_executor(pool, "process") not in (None, broken)
    finally:
        pool.shutdown(wait_for_interpreters=True)
