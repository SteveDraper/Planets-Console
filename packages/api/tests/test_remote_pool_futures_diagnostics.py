"""Tests for remote pool future probes in compute diagnostics."""

from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import MagicMock

from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.in_flight import InFlightPoolExecution
from api.compute.diagnostics.snapshot import (
    build_compute_diagnostics_snapshot,
    snapshot_to_wire,
)
from api.compute.pools import ComputeWorkerPool, PoolWorkItem
from api.compute.remote_futures import (
    classify_future_state,
    future_exception_type,
    remote_future_record,
)
from api.compute.scope import ComputeScope
from api.compute.wire import StepResult


def _scope() -> ComputeScope:
    return ComputeScope(
        analytic_id="fleet",
        game_id=628580,
        perspective=11,
        turn=5,
        player_id=3,
    )


def test_classify_future_state_pending_running_done_cancelled():
    pending: Future[object] = Future()
    assert classify_future_state(pending) == "pending"

    running: Future[object] = Future()
    running.set_running_or_notify_cancel()
    assert classify_future_state(running) == "running"

    done: Future[object] = Future()
    done.set_result({"ok": True})
    assert classify_future_state(done) == "done"
    assert future_exception_type(done) is None

    failed: Future[object] = Future()
    failed.set_exception(RuntimeError("boom"))
    assert classify_future_state(failed) == "done"
    assert future_exception_type(failed) == "RuntimeError"

    cancelled: Future[object] = Future()
    cancelled.cancel()
    assert classify_future_state(cancelled) == "cancelled"


def test_snapshot_joins_remote_future_state_onto_in_flight():
    scope = _scope()
    shell = ShellContextKey(game_id=scope.game_id, perspective=scope.perspective, turn=scope.turn)
    future: Future[object] = Future()
    future.set_result({"ok": True})
    remote = remote_future_record(
        orchestrator_id=1,
        scope=scope,
        step_kind="materialization_leg",
        step_index=0,
        priority_band="stream_attached",
        backend="interpreter",
        future=future,
    )
    in_flight = InFlightPoolExecution(
        scope=scope,
        scope_key="fleet@g628580@p11@t5@pl3",
        analytic_id="fleet",
        step_kind="materialization_leg",
        step_index=0,
        priority_band="stream_attached",
        backend="interpreter",
        orchestrator_id=1,
        started_at="2026-07-13T00:00:00+00:00",
    )
    snapshot = build_compute_diagnostics_snapshot(
        shell=shell,
        ancestor_turns=frozenset({scope.turn}),
        freeze_armed=False,
        allowlisted_player_ids=frozenset(),
        bound_orchestrators=(),
        pool_queue_items=(),
        pool_item_is_runnable=None,
        in_flight=(in_flight,),
        next_single_step=None,
        single_step_disabled_reason="freeze_not_armed",
        completion_history=(),
        remote_futures=(remote,),
        remote_executor_probe={
            "interpreterMaxWorkers": 4,
            "processMaxWorkers": None,
            "interpreterQueueDepth": 0,
            "processQueueDepth": None,
        },
    )
    wire = snapshot_to_wire(snapshot)
    assert len(wire["inFlight"]) == 1
    assert wire["inFlight"][0]["futureState"] == "done"
    assert wire["inFlight"][0]["futureExceptionType"] is None
    assert wire["remotePool"]["interpreter"]["counts"]["done"] == 1
    assert wire["remotePool"]["interpreter"]["maxWorkers"] == 4
    assert wire["remotePool"]["interpreter"]["futures"][0]["futureState"] == "done"


def test_pool_registers_remote_future_on_interpreter_submit_and_clears_after_done():
    """Executor submit retains the Future until the done callback finishes."""
    pool = ComputeWorkerPool(worker_count=0)
    try:
        orch = MagicMock()
        orch_id = pool.register(orch)
        pending: Future[object] = Future()
        executor = MagicMock()
        executor.submit.return_value = pending

        item = PoolWorkItem(
            orchestrator_id=orch_id,
            scope=_scope(),
            step_kind="materialization_leg",
            backend="interpreter",
            priority_band="background",
            step_index=0,
            job_wire={"x": 1},
            run_step=lambda _job: StepResult(outcome="complete", payload={"ok": True}),
        )
        pool._interpreter_executor = executor  # type: ignore[assignment]
        pool._execute_item(item)

        records = pool.snapshot_remote_futures()
        assert len(records) == 1
        assert records[0].future is pending
        assert classify_future_state(pending) == "pending"
        probe = pool.remote_executor_probe()
        assert probe["interpreterMaxWorkers"] == pool.worker_count

        pending.set_result(StepResult(outcome="complete", payload={"ok": True}))
        assert pool.snapshot_remote_futures() == ()
        orch.complete_pool_step.assert_called_once()
    finally:
        pool.shutdown(wait_for_interpreters=False)


def test_remote_future_unregister_does_not_take_pool_condition_under_controller():
    """Done-callback unregister must not ABBA with on_dequeued (pool→controller).

    Worker holds the pool condition and waits to take the controller lock; the done
    callback holds the controller lock and then unregisters. Unregister must not
    need the pool condition or those two threads deadlock.
    """
    import threading

    pool = ComputeWorkerPool(worker_count=0)
    controller_lock = threading.Lock()
    worker_holds_pool = threading.Event()
    callback_holds_controller = threading.Event()
    done_finished = threading.Event()
    worker_finished = threading.Event()

    try:
        item = PoolWorkItem(
            orchestrator_id=0,
            scope=_scope(),
            step_kind="materialization_leg",
            backend="interpreter",
            priority_band="background",
            step_index=0,
            job_wire={"x": 1},
            run_step=lambda _job: StepResult(outcome="complete", payload={"ok": True}),
        )
        future: Future[object] = Future()
        pool._register_remote_future(item, future)

        def worker_holds_pool_then_controller() -> None:
            with pool._condition:
                worker_holds_pool.set()
                assert callback_holds_controller.wait(timeout=5.0)
                with controller_lock:
                    pass
            worker_finished.set()

        def done_callback_controller_then_unregister() -> None:
            assert worker_holds_pool.wait(timeout=5.0)
            with controller_lock:
                callback_holds_controller.set()
                # Mirrors ``_on_remote_future_done`` finally after notify.
                pool._unregister_remote_future(future)
            done_finished.set()

        worker = threading.Thread(target=worker_holds_pool_then_controller, daemon=True)
        callback = threading.Thread(target=done_callback_controller_then_unregister, daemon=True)
        worker.start()
        callback.start()
        assert done_finished.wait(timeout=2.0), "unregister deadlocked on pool condition"
        assert worker_finished.wait(timeout=2.0), "worker deadlocked on controller lock"
        worker.join(timeout=1.0)
        callback.join(timeout=1.0)
        assert pool.snapshot_remote_futures() == ()
    finally:
        callback_holds_controller.set()
        pool.shutdown(wait_for_interpreters=False)
