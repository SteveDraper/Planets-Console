"""Regression tests for cancelled tier jobs and stale persistence."""

from __future__ import annotations

import threading
import time

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import (
    TierJobOutcome,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend


def _session_for_player(
    sample_turn,
    *,
    player_id: int,
    game_id: int = 628580,
    perspective: int = 1,
) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=sample_turn.settings.turn,
    )


def _wait_until(predicate, *, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def test_cancelled_tier_job_does_not_persist_after_run_removed(sample_turn, monkeypatch):
    """A zombie worker must not persist or resurrect a row run cancelled mid-tier."""
    reset_inference_row_scheduler_for_tests()
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler(
        worker_count=1,
        on_row_complete=persistence.persist_row_complete,
    )
    try:
        scope = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=sample_turn.settings.turn,
        )
        scheduler.begin_scope(scope)

        tier_step_started = threading.Event()
        tier_step_gate = threading.Event()

        outcome_computed = threading.Event()
        release_outcome = threading.Event()

        short_ladder = resolve_tier_policies(None)[:1]

        def fake_tier_step(
            state: PolicyLadderState,
            observation,
            turn,
            *,
            time_limit_seconds=None,
            cancel_token=None,
            on_admitted=None,
        ) -> None:
            tier_step_started.set()
            tier_step_gate.wait(timeout=2.0)
            state.policy_steps_attempted.append(state.policy_steps[state.next_step_index].id)
            state.next_step_index += 1
            state.ladder_complete = True

        real_run_inference_tier_job = run_inference_tier_job

        def gated_run_inference_tier_job(run, callbacks):
            real_run_inference_tier_job(run, callbacks)
            outcome = TierJobOutcome(
                row_complete=row_complete_with_summary(
                    InferenceResult(
                        status=STATUS_NO_EXACT_SOLUTION,
                        solutions=(),
                        diagnostics={},
                    ),
                    summary="zombie tier result",
                ),
            )
            outcome_computed.set()
            release_outcome.wait(timeout=2.0)
            return outcome

        monkeypatch.setattr(
            "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
            fake_tier_step,
        )
        monkeypatch.setattr(
            "api.analytics.military_score_inference.inference_scheduler.run_inference_tier_job",
            gated_run_inference_tier_job,
        )

        player_id = sample_turn.scores[0].ownerid
        session = _session_for_player(sample_turn, player_id=player_id)
        turn_number = sample_turn.settings.turn

        scheduler.enqueue_tier_ladder(session)
        scheduler._runs[session.run_id].ladder_state = PolicyLadderState(
            policy_steps=short_ladder,
        )

        _wait_until(tier_step_started.is_set)
        scheduler.cancel_row_run(run_id := session.run_id)
        persistence.delete_row(628580, 1, turn_number, player_id)
        tier_step_gate.set()

        _wait_until(outcome_computed.is_set)

        release_outcome.set()

        _wait_until(
            lambda: all(job.session.run_id != run_id for job in scheduler._work_queue),
            timeout_seconds=3.0,
        )
        time.sleep(0.05)

        assert persistence.get_row(628580, 1, turn_number, player_id) is None
        assert run_id not in scheduler._runs
        assert all(job.session.run_id != run_id for job in scheduler._work_queue)
    finally:
        reset_inference_row_scheduler_for_tests()


def test_cancel_between_tier_finish_and_emit_does_not_persist(sample_turn, monkeypatch):
    """Cancel after tier work returns but before row-complete persist must not write storage."""
    reset_inference_row_scheduler_for_tests()
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler(
        worker_count=1,
        on_row_complete=persistence.persist_row_complete,
    )
    try:
        scope = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=sample_turn.settings.turn,
        )
        scheduler.begin_scope(scope)

        emit_entered = threading.Event()
        emit_gate = threading.Event()
        original_emit = InferenceRowScheduler._emit_row_complete

        def gated_emit(self, session, event):
            emit_entered.set()
            emit_gate.wait(timeout=2.0)
            original_emit(self, session, event)

        monkeypatch.setattr(InferenceRowScheduler, "_emit_row_complete", gated_emit)

        short_ladder = resolve_tier_policies(None)[:1]

        def fast_tier_step(
            state: PolicyLadderState,
            observation,
            turn,
            *,
            time_limit_seconds=None,
            cancel_token=None,
            on_admitted=None,
        ) -> None:
            state.policy_steps_attempted.append(state.policy_steps[state.next_step_index].id)
            state.next_step_index += 1
            state.ladder_complete = True

        monkeypatch.setattr(
            "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
            fast_tier_step,
        )

        player_id = sample_turn.scores[0].ownerid
        session = _session_for_player(sample_turn, player_id=player_id)
        turn_number = sample_turn.settings.turn

        scheduler.enqueue_tier_ladder(session)
        scheduler._runs[session.run_id].ladder_state = PolicyLadderState(
            policy_steps=short_ladder,
        )

        _wait_until(emit_entered.is_set)
        scheduler.cancel_row_run(run_id := session.run_id)
        persistence.delete_row(628580, 1, turn_number, player_id)
        emit_gate.set()

        _wait_until(lambda: run_id not in scheduler._runs, timeout_seconds=3.0)
        time.sleep(0.05)

        assert persistence.get_row(628580, 1, turn_number, player_id) is None
        assert run_id not in scheduler._runs
    finally:
        reset_inference_row_scheduler_for_tests()
