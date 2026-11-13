"""``row_run_for_player`` reads the registry's indexed run for the scope."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores.tier_row_run_registry import (
    _detach_row_run,
    get_row_run,
    reset_tier_row_run_registry_for_tests,
)

from tests.scores_row_lifecycle_test_helpers import _session_for_player

GAME_ID = 628580
PERSPECTIVE = 1


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()


@pytest.fixture
def scheduler() -> InferenceRowScheduler:
    return InferenceRowScheduler(defer_orchestrator_submit=True)


def _stream_scope(sample_turn) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn_number=sample_turn.settings.turn,
    )


def test_the_indexed_run_wins_over_an_earlier_registered_duplicate(sample_turn, scheduler):
    player_id = sample_turn.scores[0].ownerid
    stale = _session_for_player(sample_turn, player_id=player_id)
    winner = _session_for_player(sample_turn, player_id=player_id)
    scheduler.enqueue_tier_ladder(stale)
    stream_token = scheduler.begin_scope(_stream_scope(sample_turn))
    scheduler.enqueue_tier_ladder(winner, stream_token=stream_token)
    assert get_row_run(stale.run_id) is not None
    assert list(scheduler._runs) == [stale.run_id, winner.run_id]

    run = scheduler.row_run_for_player(_stream_scope(sample_turn), player_id)

    assert run is not None
    assert run.run_id == winner.run_id


def test_no_run_for_a_player_with_no_registered_run(sample_turn, scheduler):
    player_id = sample_turn.scores[0].ownerid
    other_player_id = sample_turn.scores[1].ownerid
    scheduler.enqueue_tier_ladder(_session_for_player(sample_turn, player_id=player_id))

    assert scheduler.row_run_for_player(_stream_scope(sample_turn), other_player_id) is None


def test_a_detached_run_is_not_returned(sample_turn, scheduler):
    player_id = sample_turn.scores[0].ownerid
    session = _session_for_player(sample_turn, player_id=player_id)
    scheduler.enqueue_tier_ladder(session)
    _detach_row_run(session.run_id)

    assert scheduler.row_run_for_player(_stream_scope(sample_turn), player_id) is None
