"""An accelerated split segment orchestration for tests that drive segment ladders.

The split solves an accel window segment, then the reported host turn segment.
"""

from __future__ import annotations

from api.analytics.military_score_inference.accelerated_start import (
    ACCEL_WINDOW_SEGMENT_ID,
    REPORTED_HOST_TURN_SEGMENT_ID,
    AcceleratedInferenceSegment,
)
from api.analytics.military_score_inference.inference_path import InferencePath
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.models.player import Score


def accelerated_split_orchestration(turn, score: Score) -> InferenceStreamOrchestration:
    """Two segments for ``score`` on ``turn``, with neither solved yet."""
    return InferenceStreamOrchestration(
        path=InferencePath.ACCELERATED_SPLIT,
        row_score=score,
        row_turn=turn,
        solve_score=score,
        solve_turn=turn,
        segments=(
            AcceleratedInferenceSegment(
                segment_id=ACCEL_WINDOW_SEGMENT_ID,
                host_turn=1,
                military_delta_2x=110,
                warship_delta=0,
                freighter_delta=1,
                priority_point_delta=0,
            ),
            AcceleratedInferenceSegment(
                segment_id=REPORTED_HOST_TURN_SEGMENT_ID,
                host_turn=2,
                military_delta_2x=20,
                warship_delta=1,
                freighter_delta=0,
                priority_point_delta=0,
            ),
        ),
    )
