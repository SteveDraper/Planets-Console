"""One scoreboard row's tier ladder, as a single value.

A ladder is the policy ladder state plus, for a row solved in accelerated
segments (split or backfill), the segment orchestration that records each
segment's solve. The two belong together: hand-over moves both to another
run, and progress in one without the other would combine segments from
different ladders. ``TierLadder`` is frozen, so a run's ladder changes only by
replacing the whole value.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState


@dataclass(frozen=True, slots=True)
class TierLadder:
    """A row's policy ladder state and, when it solves in segments, their orchestration.

    ``orchestration`` is None for a row that solves one segment (no accelerated
    split or backfill).
    """

    ladder_state: PolicyLadderState
    orchestration: InferenceStreamOrchestration | None = None
