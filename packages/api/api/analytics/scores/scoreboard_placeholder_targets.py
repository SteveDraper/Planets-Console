"""Scoreboard placeholder build counts exposed through the scores analytic."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.accelerated_start import (
    HOMEBASE_STARTING_FREIGHTER_HULL_ID,
    accelerated_inference_segments,
    starting_scoreboard_snapshot,
)
from api.models.game import TurnInfo
from api.models.player import Score


@dataclass(frozen=True)
class ScoreboardPlaceholderTarget:
    """One inferred placeholder group keyed by host turn."""

    host_turn: int
    warship_delta: int
    freighter_delta: int
    segment_id: str | None = None


def homeworld_starting_freighter_hull_id() -> int:
    return HOMEBASE_STARTING_FREIGHTER_HULL_ID


def homeworld_starting_inventory_counts(turn: TurnInfo) -> tuple[int, int]:
    """Return (freighters, warships) seeded at game start."""
    baseline = starting_scoreboard_snapshot(turn.settings)
    return baseline.freighters, baseline.capitalships


def scoreboard_placeholder_targets(
    score: Score,
    turn: TurnInfo,
) -> tuple[ScoreboardPlaceholderTarget, ...] | None:
    """Return accelerated segment placeholder targets on the first reliable row."""
    segments = accelerated_inference_segments(score, turn)
    if segments is None:
        return None
    return tuple(
        ScoreboardPlaceholderTarget(
            host_turn=segment.host_turn,
            warship_delta=segment.warship_delta,
            freighter_delta=segment.freighter_delta,
            segment_id=segment.segment_id,
        )
        for segment in segments
    )
