"""A tier ladder's segment orchestration restarts with its segments and without its progress."""

from __future__ import annotations

from tests.accelerated_segment_helpers import accelerated_split_orchestration


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
