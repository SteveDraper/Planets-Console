"""Scoreboard placeholder build counts exposed through the scores analytic."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.accelerated_start import (
    HOMEBASE_STARTING_FREIGHTER_HULL_ID,
    accelerated_inference_segments,
    is_first_reliable_scoreboard_turn,
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


def homeworld_starting_freighter_hull_id() -> int:
    return HOMEBASE_STARTING_FREIGHTER_HULL_ID


def homeworld_starting_inventory_counts(turn: TurnInfo) -> tuple[int, int]:
    """Return (freighters, warships) seeded at game start."""
    baseline = starting_scoreboard_snapshot(turn.settings)
    return baseline.freighters, baseline.capitalships


def is_first_reliable_accelerated_shell_turn(shell_turn: int, turn: TurnInfo) -> bool:
    """Return whether this shell turn is the first reliable accelerated scoreboard row."""
    return is_first_reliable_scoreboard_turn(shell_turn, turn.settings)


def should_seed_homeworld_starting_inventory(turn: TurnInfo) -> bool:
    """Return whether homeworld starting ships should be seeded on this shell turn."""
    return is_first_reliable_accelerated_shell_turn(turn.settings.turn, turn)


def scoreboard_placeholder_targets(
    score: Score,
    turn: TurnInfo,
) -> tuple[ScoreboardPlaceholderTarget, ...] | None:
    """Return placeholder build targets for accelerated segments or normal scoreboard deltas."""
    segments = accelerated_inference_segments(score, turn)
    if segments is not None:
        return tuple(
            ScoreboardPlaceholderTarget(
                host_turn=segment.host_turn,
                warship_delta=segment.warship_delta,
                freighter_delta=segment.freighter_delta,
            )
            for segment in segments
        )

    turn_number = turn.settings.turn
    targets: list[ScoreboardPlaceholderTarget] = []
    warship_builds = max(0, score.shipchange)
    freighter_builds = max(0, score.freighterchange)
    if warship_builds > 0:
        targets.append(
            ScoreboardPlaceholderTarget(
                host_turn=turn_number,
                warship_delta=warship_builds,
                freighter_delta=0,
            )
        )
    if freighter_builds > 0:
        targets.append(
            ScoreboardPlaceholderTarget(
                host_turn=turn_number,
                warship_delta=0,
                freighter_delta=freighter_builds,
            )
        )
    return tuple(targets) if targets else None
