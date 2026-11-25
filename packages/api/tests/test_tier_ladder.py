"""A scoreboard row's tier ladder is one value: ladder state plus segment orchestration."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_row_runner import TierJobContinue
from api.analytics.scores.tier_row_run_registry import get_row_run

from tests.accelerated_segment_helpers import accelerated_split_orchestration

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


def test_a_restarted_orchestration_clears_progress_and_keeps_its_segments(sample_turn):
    orchestration = accelerated_split_orchestration(sample_turn, sample_turn.scores[0])
    orchestration.current_segment_index = 1
    orchestration.combined_time_limited = True
    orchestration.segment_solves.append(object())  # type: ignore[arg-type]
    orchestration.resolved_mask = object()  # type: ignore[assignment]

    restarted = orchestration.restarted()

    assert restarted is not orchestration
    assert restarted.current_segment_index == 0
    assert restarted.segment_solves == []
    assert restarted.combined_time_limited is False
    assert restarted.resolved_mask is None
    assert restarted.segments == orchestration.segments
    assert restarted.path is orchestration.path
    assert orchestration.current_segment_index == 1


def test_a_hand_over_moves_the_ladder_as_one_value(ladder):
    ladder.submit()
    stamped_id = ladder.session.run_id
    ladder.run_tier(TierJobContinue())
    ladder.close_stream()
    winner_id = ladder.open_stream().run_id
    stamped_ladder = get_row_run(stamped_id).ladder

    ladder.build_wire()

    assert get_row_run(winner_id).ladder is stamped_ladder
