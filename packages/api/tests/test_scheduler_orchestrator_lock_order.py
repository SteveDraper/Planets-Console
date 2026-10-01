"""Scheduler locks must not be held while acquiring the orchestrator condition.

Fleet and scores attach to the process orchestrator once per scheduler
(``SchedulerOrchestratorAttachment``). Stream preempt, end, pause, and detach
only mutate scheduler maps, so a caller that already holds the orchestrator
condition can finish them.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from api.analytics.fleet.fleet_table_stream_scheduler import FleetTableStreamScheduler
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE_PROFILE_INDEX
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator_observers import OrchestratorObservers
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests


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


def test_scores_pause_and_detach_return_while_orchestrator_condition_held() -> None:
    scheduler = InferenceRowScheduler()
    scope = _scores_scope()
    token = scheduler.begin_scope(scope)
    orchestrator = get_compute_orchestrator()
    orchestrator_held = threading.Event()
    finished = threading.Event()
    errors: list[str] = []

    def _pause_and_detach() -> None:
        assert orchestrator_held.wait(timeout=2)
        scheduler.pause_globally(scope)
        scheduler.detach_inference_stream(scope, (), stream_token=token)
        finished.set()

    worker = threading.Thread(target=_pause_and_detach)
    worker.start()
    try:
        with orchestrator._condition:
            orchestrator_held.set()
            if not finished.wait(timeout=2):
                errors.append(
                    "scores pause/detach blocked while the orchestrator condition was held"
                )
            else:
                acquired = scheduler._lock.acquire(timeout=1)
                if not acquired:
                    errors.append("inference scheduler lock still held after pause/detach")
                else:
                    scheduler._lock.release()
        worker.join(timeout=2)
        if worker.is_alive():
            errors.append(
                "scores pause/detach thread still blocked after the condition was released"
            )
        assert errors == []
    finally:
        scheduler.shutdown()
