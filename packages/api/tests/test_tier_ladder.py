"""A scoreboard row's tier ladder is one value: ladder state plus segment orchestration."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.accelerated_start import (
    ACCEL_WINDOW_SEGMENT_ID,
    REPORTED_HOST_TURN_SEGMENT_ID,
    AcceleratedInferenceSegment,
)
from api.analytics.military_score_inference.inference_path import InferencePath
from api.analytics.military_score_inference.inference_row_runner import TierJobContinue
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.scores.compute_orchestration import build_scores_tier_solve_job_wire
from api.analytics.scores.tier_row_run_registry import get_row_run
from api.compute.wire import DependencyOutputs

from tests.submission_open_helpers import explicit_submission_open, live_execution

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


def _segment(segment_id: str, host_turn: int) -> AcceleratedInferenceSegment:
    return AcceleratedInferenceSegment(
        segment_id=segment_id,
        host_turn=host_turn,
        military_delta_2x=20,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
    )


def _split_orchestration(sample_turn) -> InferenceStreamOrchestration:
    score = sample_turn.scores[0]
    return InferenceStreamOrchestration(
        path=InferencePath.ACCELERATED_SPLIT,
        row_score=score,
        row_turn=sample_turn,
        solve_score=score,
        solve_turn=sample_turn,
        segments=(
            _segment(ACCEL_WINDOW_SEGMENT_ID, 1),
            _segment(REPORTED_HOST_TURN_SEGMENT_ID, 2),
        ),
    )


def test_a_restarted_orchestration_clears_progress_and_keeps_its_segments(sample_turn):
    orchestration = _split_orchestration(sample_turn)
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

    build_scores_tier_solve_job_wire(
        ladder.scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ladder.ctx,
        submission_open=explicit_submission_open(),
        execution_generation=ladder.orchestrator.nodes[ladder.scope].execution_generation,
        is_execution_live=live_execution,
    )

    assert get_row_run(winner_id).ladder is stamped_ladder
