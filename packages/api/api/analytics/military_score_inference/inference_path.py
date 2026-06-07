"""Resolve which inference orchestration path applies for a scoreboard row."""

from __future__ import annotations

from enum import Enum

from api.analytics.military_score_inference.accelerated_start import (
    AcceleratedInferenceSegment,
    accelerated_inference_segments,
    accelerated_turn_count,
    scoreboard_host_turn,
)
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_target import (
    ScoreboardTurnLoader,
    load_accelerated_backfill_source_for_host_turn,
)
from api.models.game import TurnInfo
from api.models.player import Score


class InferencePath(Enum):
    """High-level inference orchestration path for one scoreboard row."""

    CORPUS_PREBUILT = "corpus_prebuilt"
    ACCELERATED_BACKFILL = "accelerated_backfill"
    ACCELERATED_SPLIT = "accelerated_split"
    POLICY_LADDER = "policy_ladder"
    NO_PRIOR_TURN = "no_prior_turn"


def prior_turn_score_data_available(turn: TurnInfo) -> bool:
    """Return whether this turn has a prior scoreboard row to infer from."""
    turn_number = turn.settings.turn
    if turn_number <= 1:
        return False
    accelerated = accelerated_turn_count(turn.settings)
    if accelerated > 0 and turn_number < accelerated:
        return False
    return True


def _can_attempt_accelerated_backfill(
    score: Score,
    turn: TurnInfo,
    *,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
) -> bool:
    if load_scoreboard_turn is None:
        return False
    target_host_turn = scoreboard_host_turn(turn.settings.turn)
    if target_host_turn is None:
        return False
    return (
        load_accelerated_backfill_source_for_host_turn(
            score,
            turn,
            host_turn=target_host_turn,
            load_scoreboard_turn=load_scoreboard_turn,
        )
        is not None
    )


def resolve_inference_path(
    score: Score,
    turn: TurnInfo,
    *,
    catalog: ActionCatalog | None = None,
    load_scoreboard_turn: ScoreboardTurnLoader | None = None,
) -> tuple[InferencePath, tuple[AcceleratedInferenceSegment, ...] | None]:
    """Pick the inference orchestration path and any pre-resolved accelerated segments."""
    if not prior_turn_score_data_available(turn):
        if _can_attempt_accelerated_backfill(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
        ):
            return InferencePath.ACCELERATED_BACKFILL, None
        return InferencePath.NO_PRIOR_TURN, None

    if catalog is not None:
        return InferencePath.CORPUS_PREBUILT, None

    segments = accelerated_inference_segments(score, turn)
    if segments is not None:
        return InferencePath.ACCELERATED_SPLIT, segments

    return InferencePath.POLICY_LADDER, None
