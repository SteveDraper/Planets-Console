"""Tests for global pause/resume on the inference row scheduler."""

import pytest
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    HeldSolutionsUpdated,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceSolution, InferenceSolutionAction
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.errors import ValidationError


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


def test_pause_without_active_stream_raises_validation_error(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.pause_globally(scope)

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.resume_globally(scope)


def test_pause_with_mismatched_scope_raises_validation_error(sample_turn):
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

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.pause_globally(scope_b)

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.resume_globally(scope_b)


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


def test_end_inference_stream_keeps_global_pause_while_other_stream_connected(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    session_a = _session_for_turn(sample_turn)
    score_b = sample_turn.scores[1]
    session_b = InferenceRowStreamSession(
        player_id=score_b.ownerid,
        observation=build_inference_observation(score_b, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)
    scheduler.begin_scope(scope)
    scheduler.enqueue_tier_ladder(session_a)
    scheduler.enqueue_tier_ladder(session_b)
    scheduler.pause_globally(scope)

    assert scheduler.global_pause_status(scope)["paused"] is True
    assert scheduler.global_pause_status(scope)["activeSessionCount"] == 2

    scheduler.end_inference_stream(scope, (session_a,))

    status = scheduler.global_pause_status(scope)
    assert status["paused"] is True
    assert status["activeSessionCount"] == 1
    assert session_a.cancel_token.is_cancelled()
    assert not session_b.cancel_token.is_cancelled()

    scheduler.end_inference_stream(scope, (session_b,))

    status = scheduler.global_pause_status(scope)
    assert status["paused"] is False
    assert status["activeSessionCount"] == 0
    assert session_b.cancel_token.is_cancelled()


def test_end_inference_stream_cancels_runs_and_clears_global_pause(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    session = _session_for_turn(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.enqueue_tier_ladder(session)
    scheduler.pause_globally(scope)

    assert scheduler.global_pause_status(scope)["paused"] is True
    assert scheduler.global_pause_status(scope)["activeSessionCount"] == 1

    scheduler.end_inference_stream(scope, (session,))

    status = scheduler.global_pause_status(scope)
    assert status["paused"] is False
    assert status["activeSessionCount"] == 0
    assert status["heldJobCount"] == 0
    assert session.cancel_token.is_cancelled()


def test_emit_held_solutions_snapshots_merged_list(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    session = _session_for_turn(sample_turn)
    scheduler.register_session(session)
    run = scheduler._runs[session.run_id]
    run.ladder_state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    run.ladder_state.catalog = ActionCatalog((), (), {})
    run.ladder_state.merged_solutions = [
        InferenceSolution(
            objective_value=10,
            actions=(InferenceSolutionAction(action_id="a1", label="Action A", count=1),),
        )
    ]

    scheduler._emit_held_solutions(session, observation=session.observation)

    event = session.event_queue.get(timeout=1.0)
    assert isinstance(event, HeldSolutionsUpdated)
    assert len(event.solutions) == 1
    assert event.solutions[0].objective_value == 10

    run.ladder_state.merged_solutions.append(
        InferenceSolution(
            objective_value=5,
            actions=(InferenceSolutionAction(action_id="a2", label="Action B", count=1),),
        )
    )

    assert len(event.solutions) == 1
    assert event.solutions[0].objective_value == 10
