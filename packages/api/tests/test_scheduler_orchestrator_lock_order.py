"""Scheduler locks must not be held while acquiring the orchestrator condition.

Fingerprint (game 686674, perspective 21, turn 3): fleet and scores table
streams left every player in progress at 0% CPU, and the compute diagnostics
snapshot never returned. Three locks formed a ring:

- orchestrator condition held across scores ``is_satisfied`` / ``global_pause_status``
- inference scheduler lock held across mine-stock load, then a fleet-stream
  generator ``finally`` waited on the fleet scheduler lock
- fleet scheduler lock held across scope-outcome ``unregister``
"""

from __future__ import annotations

import threading
from typing import cast

import pytest
from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    _FleetStreamOrchestratorBinding,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.compute.orchestrator_observers import OrchestratorObservers
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests

from tests.scores_exports_helpers import minimal_stream_query_context


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


def test_fleet_preempt_releases_scheduler_lock_before_orchestrator_unregister() -> None:
    scheduler = FleetTableStreamScheduler()
    scope = _fleet_scope()
    scheduler.begin_scope(scope)
    orchestrator = get_compute_orchestrator()
    started_unregister = threading.Event()
    orchestrator_held = threading.Event()

    def _listener(_snapshot: object) -> None:
        return None

    unregister = orchestrator.observers.register_scope_outcome_listener(_listener)

    def _unregister_and_signal() -> None:
        started_unregister.set()
        unregister()

    token = scheduler._scope_guard.active_table_stream_token
    assert token is not None
    scheduler._stream_bindings[token] = _FleetStreamOrchestratorBinding(
        orchestrator=orchestrator,
        unregister_listener=_unregister_and_signal,
        query_context=cast(AnalyticQueryContext, object()),
    )
    errors: list[str] = []

    def _preempt() -> None:
        assert orchestrator_held.wait(timeout=2)
        scheduler.begin_scope(scope)

    worker = threading.Thread(target=_preempt)
    worker.start()
    with orchestrator._condition:
        orchestrator_held.set()
        if not started_unregister.wait(timeout=2):
            errors.append("preempt did not reach orchestrator unregister")
        else:
            acquired = scheduler._lock.acquire(timeout=1)
            if not acquired:
                errors.append(
                    "fleet scheduler lock held while unregister waited on the "
                    "orchestrator condition"
                )
            else:
                scheduler._lock.release()
    worker.join(timeout=2)
    if worker.is_alive():
        errors.append("preempt thread still blocked after the orchestrator lock was released")
    assert errors == []
    assert _listener not in orchestrator.observers._scope_outcome_listeners


def test_end_fleet_table_stream_defers_unregister_while_orchestrator_lock_held() -> None:
    scheduler = FleetTableStreamScheduler()
    scope = _fleet_scope()
    token = scheduler.begin_scope(scope)
    orchestrator = get_compute_orchestrator()

    def _listener(_snapshot: object) -> None:
        return None

    unregister = orchestrator.observers.register_scope_outcome_listener(_listener)
    scheduler._stream_bindings[token] = _FleetStreamOrchestratorBinding(
        orchestrator=orchestrator,
        unregister_listener=unregister,
        query_context=cast(AnalyticQueryContext, object()),
    )

    with orchestrator._condition:
        scheduler.end_fleet_table_stream(scope, (), stream_token=token)
        assert _listener in orchestrator.observers._scope_outcome_listeners

    orchestrator.observers.drain_post_lock_callbacks()
    assert _listener not in orchestrator.observers._scope_outcome_listeners


def test_fleet_binding_register_does_not_hold_scheduler_lock(
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
    scheduler._binding_for_stream(
        "stream-token",
        query_context=cast(AnalyticQueryContext, object()),
    )
    assert observed["scheduler_lock_free"] is True


def test_paused_enqueue_releases_scheduler_lock_before_dispatch_gate(
    sample_turn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.analytics.scores.tier_row_run_registry.register_row_run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        InferenceRowScheduler,
        "_register_tier_callbacks_for_run",
        lambda self, _row_run: None,
    )
    monkeypatch.setattr(
        InferenceRowScheduler,
        "_submit_tier_solve_locked",
        lambda self, _binding, _root_scope: None,
    )

    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    orchestrator = get_compute_orchestrator()
    entered_gate = threading.Event()
    orchestrator_held = threading.Event()
    real_register = OrchestratorObservers.register_dispatch_gate

    def _register(self: OrchestratorObservers, gate: object) -> object:
        entered_gate.set()
        return real_register(self, gate)  # type: ignore[arg-type]

    monkeypatch.setattr(OrchestratorObservers, "register_dispatch_gate", _register)

    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
        query_context=minimal_stream_query_context(
            sample_turn,
            game_id=628580,
            perspective=1,
        ),
    )
    errors: list[str] = []

    def _enqueue() -> None:
        assert orchestrator_held.wait(timeout=2)
        scheduler.enqueue_tier_ladder(session, stream_token=stream_token)

    worker = threading.Thread(target=_enqueue)
    worker.start()
    with orchestrator._condition:
        orchestrator_held.set()
        if not entered_gate.wait(timeout=2):
            errors.append("enqueue did not reach dispatch-gate registration")
        else:
            acquired = scheduler._lock.acquire(timeout=1)
            if not acquired:
                errors.append(
                    "inference scheduler lock held while dispatch-gate registration "
                    "waited on the orchestrator condition"
                )
            else:
                scheduler._lock.release()
    worker.join(timeout=2)
    if worker.is_alive():
        errors.append("enqueue thread still blocked after the orchestrator lock was released")
    try:
        assert errors == []
    finally:
        scheduler.shutdown()
