"""A scores stream ends by its token: it detaches every run it owns, and no other."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    TierLadderRegistration,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores.tier_row_run_registry import get_row_run

from tests.scores_exports_helpers import GAME_ID, perspective
from tests.scores_ladder_helpers import ladder_session

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


def _scope(sample_turn) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )


def _player_ids(sample_turn) -> list[int]:
    return [row.ownerid for row in sample_turn.scores[:2]]


def test_a_deferred_submit_stream_end_detaches_the_rows_it_owns(sample_turn) -> None:
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scope = _scope(sample_turn)
    token = scheduler.begin_scope(scope)
    session = ladder_session(sample_turn, _player_ids(sample_turn)[0])
    assert (
        scheduler.enqueue_tier_ladder(session, stream_token=token)
        is TierLadderRegistration.SUBMIT_DEFERRED
    )

    scheduler.detach_inference_stream(scope, stream_token=token)

    assert session.run_id not in scheduler._runs
    assert get_row_run(session.run_id) is None


def test_a_stream_end_detaches_a_run_registered_after_its_admissions(sample_turn) -> None:
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scope = _scope(sample_turn)
    token = scheduler.begin_scope(scope)
    first, rescheduled = (
        ladder_session(sample_turn, player_id) for player_id in _player_ids(sample_turn)
    )
    scheduler.enqueue_tier_ladder(first, stream_token=token)
    scheduler.enqueue_tier_ladder(rescheduled, stream_token=token)

    scheduler.detach_inference_stream(scope, stream_token=token)

    assert first.run_id not in scheduler._runs
    assert rescheduled.run_id not in scheduler._runs


def test_a_replaced_streams_end_leaves_the_current_streams_runs(sample_turn) -> None:
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scope = _scope(sample_turn)
    replaced = scheduler.begin_scope(scope)
    old_player, new_player = _player_ids(sample_turn)
    old_session = ladder_session(sample_turn, old_player)
    scheduler.enqueue_tier_ladder(old_session, stream_token=replaced)
    current = scheduler.begin_scope(scope)
    new_session = ladder_session(sample_turn, new_player)
    scheduler.enqueue_tier_ladder(new_session, stream_token=current)

    cleared_pause = scheduler.detach_inference_stream(scope, stream_token=replaced)

    assert cleared_pause is False
    assert old_session.run_id not in scheduler._runs
    assert new_session.run_id in scheduler._runs
    assert scheduler.owns_table_stream(current)


def test_a_background_run_is_not_ended_by_a_stream(sample_turn) -> None:
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scope = _scope(sample_turn)
    token = scheduler.begin_scope(scope)
    background = ladder_session(sample_turn, _player_ids(sample_turn)[0])
    scheduler.enqueue_tier_ladder(background)

    scheduler.detach_inference_stream(scope, stream_token=token)

    assert background.run_id in scheduler._runs


def test_a_stream_end_reports_whether_it_cleared_pause(sample_turn) -> None:
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    scope = _scope(sample_turn)
    token = scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    try:
        assert scheduler.detach_inference_stream(scope, stream_token=token) is True
    finally:
        scheduler.shutdown()
