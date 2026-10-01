"""Scheduler locks must not be held while acquiring the orchestrator condition.

Fleet and scores attach to the process orchestrator once per scheduler
(``SchedulerOrchestratorAttachment``). Stream preempt, end, and detach only
mutate scheduler maps, so a caller that already holds the orchestrator
condition can finish them. Pause status peeks that orchestrator after
releasing the scheduler lock, so the lock stays free while the peek waits.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import cast

import pytest
from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.fleet_table_stream_scheduler import FleetTableStreamScheduler
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_teardown import (
    InferenceStreamOrchestratorBinding,
)
from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE_PROFILE_INDEX
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator_observers import OrchestratorObservers
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
from api.compute.scope import ComputeScope


@pytest.fixture(autouse=True)
def _reset_process_compute_state():
    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    yield
    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=1)


def _fleet_scope() -> FleetTableStreamScope:
    return FleetTableStreamScope(game_id=686674, perspective=21, turn_number=3)


def _scores_scope() -> InferenceStreamScope:
    return InferenceStreamScope(game_id=686674, perspective=21, turn_number=3)


def _listener_count(scheduler: FleetTableStreamScheduler) -> int:
    listeners = get_compute_orchestrator().observers._scope_outcome_listeners
    return sum(1 for listener in listeners if listener == scheduler._on_orchestrator_scope_outcome)


def test_fleet_listener_registers_once_outside_the_scheduler_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = FleetTableStreamScheduler()
    observed: dict[str, bool] = {}
    real_register = OrchestratorObservers.register_scope_outcome_listener

    def _register(self: OrchestratorObservers, listener: object) -> object:
        acquired = scheduler._lock.acquire(blocking=False)
        observed["scheduler_lock_free"] = acquired
        if acquired:
            scheduler._lock.release()
        return real_register(self, listener)  # type: ignore[arg-type]

    monkeypatch.setattr(OrchestratorObservers, "register_scope_outcome_listener", _register)
    scope = _fleet_scope()
    first = scheduler.begin_scope(scope)
    second = scheduler.begin_scope(scope)
    scheduler.end_fleet_table_stream(scope, (), stream_token=second)
    assert first != second
    assert observed["scheduler_lock_free"] is True
    assert _listener_count(scheduler) == 1


def test_fleet_preempt_and_end_return_while_orchestrator_condition_held() -> None:
    scheduler = FleetTableStreamScheduler()
    scope = _fleet_scope()
    scheduler.begin_scope(scope)
    orchestrator = get_compute_orchestrator()
    orchestrator_held = threading.Event()
    finished = threading.Event()
    errors: list[str] = []

    def _preempt_and_end() -> None:
        assert orchestrator_held.wait(timeout=2)
        token = scheduler.begin_scope(scope)
        scheduler.end_fleet_table_stream(scope, (), stream_token=token)
        finished.set()

    worker = threading.Thread(target=_preempt_and_end)
    worker.start()
    with orchestrator._condition:
        orchestrator_held.set()
        if not finished.wait(timeout=2):
            errors.append("fleet preempt/end blocked while the orchestrator condition was held")
        else:
            acquired = scheduler._lock.acquire(timeout=1)
            if not acquired:
                errors.append("fleet scheduler lock still held after preempt/end")
            else:
                scheduler._lock.release()
    worker.join(timeout=2)
    if worker.is_alive():
        errors.append("fleet preempt/end thread still blocked after the condition was released")
    assert errors == []
    assert _listener_count(scheduler) == 1


def test_scores_pause_gate_is_registered_once_and_follows_the_pause_flag() -> None:
    scheduler = InferenceRowScheduler()
    scope = _scores_scope()
    token = scheduler.begin_scope(scope)
    orchestrator = get_compute_orchestrator()
    gate = scheduler._pause_dispatch_gate
    assert orchestrator.observers.dispatch_gates.count(gate) == 1

    node = SimpleNamespace(
        scope=SimpleNamespace(analytic_id=SCORES_ANALYTIC_ID),
        profile_step_index=SCORES_TIER_SOLVE_PROFILE_INDEX,
    )
    assert gate(node) is True
    scheduler.pause_globally(scope)
    assert gate(node) is False
    assert orchestrator.observers.dispatch_gates.count(gate) == 1
    scheduler.detach_inference_stream(scope, (), stream_token=token)
    assert gate(node) is True
    assert orchestrator.observers.dispatch_gates.count(gate) == 1
    scheduler.shutdown()
    assert gate not in orchestrator.observers.dispatch_gates


def test_scores_pause_rebinds_dispatch_gate_after_orchestrator_reset() -> None:
    scheduler = InferenceRowScheduler()
    scope = _scores_scope()
    scheduler.begin_scope(scope)
    reset_orchestrators_for_tests()
    scheduler.pause_globally(scope)
    orchestrator = get_compute_orchestrator()
    gate = scheduler._pause_dispatch_gate
    node = SimpleNamespace(
        scope=SimpleNamespace(analytic_id=SCORES_ANALYTIC_ID),
        profile_step_index=SCORES_TIER_SOLVE_PROFILE_INDEX,
    )
    try:
        assert orchestrator.observers.dispatch_gates.count(gate) == 1
        assert gate(node) is False
    finally:
        scheduler.shutdown()


def test_scores_pause_peek_leaves_scheduler_lock_free_and_detach_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = InferenceRowScheduler()
    scope = _scores_scope()
    token = scheduler.begin_scope(scope)
    orchestrator = get_compute_orchestrator()
    # Pause status reads binding.orchestrator. Query context is unused on this path.
    scheduler._stream_bindings[token] = InferenceStreamOrchestratorBinding(
        orchestrator=orchestrator,
        query_context=cast(AnalyticQueryContext, SimpleNamespace()),
    )
    entered_peek = threading.Event()
    real_peek = orchestrator.peek_ready_step_indexes

    def _peek(scopes: tuple[ComputeScope, ...]) -> dict[ComputeScope, int]:
        entered_peek.set()
        return real_peek(scopes)

    monkeypatch.setattr(orchestrator, "peek_ready_step_indexes", _peek)
    orchestrator_held = threading.Event()
    pause_finished = threading.Event()
    detach_go = threading.Event()
    finished = threading.Event()
    errors: list[str] = []
    pause_blocked_without_scheduler_lock = False

    def _pause_then_detach() -> None:
        assert orchestrator_held.wait(timeout=2)
        scheduler.pause_globally(scope)
        pause_finished.set()
        assert detach_go.wait(timeout=2)
        scheduler.detach_inference_stream(scope, (), stream_token=token)
        finished.set()

    worker = threading.Thread(target=_pause_then_detach)
    worker.start()
    try:
        with orchestrator._condition:
            orchestrator_held.set()
            if not entered_peek.wait(timeout=2):
                errors.append("pause did not reach the orchestrator peek")
            else:
                acquired = scheduler._lock.acquire(timeout=1)
                if not acquired:
                    errors.append(
                        "inference scheduler lock held while pause waited on the "
                        "orchestrator condition"
                    )
                else:
                    scheduler._lock.release()
                    pause_blocked_without_scheduler_lock = True
        if pause_blocked_without_scheduler_lock and not pause_finished.wait(timeout=2):
            errors.append("pause did not finish after the orchestrator condition was released")
        elif pause_blocked_without_scheduler_lock:
            with orchestrator._condition:
                detach_go.set()
                if not finished.wait(timeout=2):
                    errors.append("scores detach blocked while the orchestrator condition was held")
                else:
                    acquired = scheduler._lock.acquire(timeout=1)
                    if not acquired:
                        errors.append("inference scheduler lock still held after detach")
                    else:
                        scheduler._lock.release()
        worker.join(timeout=2)
        if worker.is_alive():
            errors.append("scores pause/detach thread still blocked")
        assert errors == []
    finally:
        detach_go.set()
        worker.join(timeout=2)
        scheduler.shutdown()
