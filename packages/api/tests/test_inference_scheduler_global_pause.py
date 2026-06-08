"""Tests for global pause/resume on the inference row scheduler."""

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    InferenceRowStreamSession,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope


def _session_for_turn(
    sample_turn,
    *,
    game_id: int = 628580,
    perspective: int = 1,
) -> InferenceRowStreamSession:
    score = sample_turn.scores[0]
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=sample_turn.settings.turn,
    )


def test_pause_holds_enqueued_jobs_and_resume_requeues(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)
    session = _session_for_turn(sample_turn)
    scheduler.enqueue_tier_ladder(session)

    paused = scheduler.pause_globally(scope)
    assert paused["paused"] is True
    assert paused["heldJobCount"] == 1

    status = scheduler.global_pause_status(scope)
    assert status["paused"] is True

    resumed = scheduler.resume_globally(scope)
    assert resumed["paused"] is False
    assert resumed["heldJobCount"] == 0


def test_new_scope_invalidates_retained_pause_state(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope_a = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scope_b = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn + 1,
    )
    scheduler.begin_scope(scope_a)
    scheduler.pause_globally(scope_a)
    scheduler.begin_scope(scope_b)

    status = scheduler.global_pause_status(scope_a)
    assert status["paused"] is False
    assert status["activeScope"]["turn"] == scope_b.turn_number


def test_preserve_session_on_stream_end_when_globally_paused(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    session = _session_for_turn(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.register_session(session)
    scheduler.pause_globally(scope)

    assert scheduler.preserve_session_on_stream_end(session) is True

    scheduler.resume_globally(scope)
    assert scheduler.preserve_session_on_stream_end(session) is False
