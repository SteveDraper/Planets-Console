"""Resolve inference catalog context for a host turn, including accelerated backfill."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.military_score_inference.accelerated_start import (
    SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
    AcceleratedInferenceSegment,
    accelerated_inference_segments,
    first_reliable_accelerated_scoreboard_turn,
    needs_accelerated_backfill,
    observation_deltas_from_score,
    scoreboard_host_turn,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.models.game import TurnInfo
from api.models.player import Score

ScoreboardTurnLoader = Callable[[int], TurnInfo | None]


@dataclass(frozen=True)
class ResolvedInferenceTarget:
    """Observation and turn snapshot used to build the action catalog for one host turn."""

    observation: InferenceObservation
    turn_info: TurnInfo
    score: Score


@dataclass(frozen=True)
class AcceleratedBackfillSource:
    """First reliable scoreboard turn and accelerated segments for backfill."""

    source_turn: TurnInfo
    source_score: Score
    segments: tuple[AcceleratedInferenceSegment, ...]
    source_turn_number: int


def is_after_ship_limit(turn: TurnInfo, score: Score) -> bool:
    """Return whether ship-limit queue rules apply for this player on this turn."""
    settings = turn.settings
    player_ships = score.capitalships + score.freighters
    if settings.shiplimittype != 0:
        player_limit = (
            settings.plsminships
            + settings.plsextraships
            + settings.plsshipsperplanet * score.planets
        )
        return player_ships >= player_limit
    total_ships = sum(
        other_score.capitalships + other_score.freighters for other_score in turn.scores
    )
    return total_ships >= settings.shiplimit


def prior_scoreboard_row_score(
    score: Score,
    turn: TurnInfo,
    load_scoreboard_turn: ScoreboardTurnLoader | None,
) -> Score | None:
    if load_scoreboard_turn is None:
        return None
    prior_turn_number = turn.settings.turn - 1
    if prior_turn_number < 1:
        return None
    prior_turn = load_scoreboard_turn(prior_turn_number)
    if prior_turn is None:
        return None
    return next((row for row in prior_turn.scores if row.ownerid == score.ownerid), None)


def observation_from_deltas(
    score: Score,
    turn: TurnInfo,
    deltas: tuple[int, int, int, int],
    *,
    military_partition_slack_2x: int = SCOREBOARD_MILITARY_PARTITION_SLACK_2X,
    scoreboard_delta_source: str = "reported_change_fields",
) -> InferenceObservation:
    military_delta_2x, warship_delta, freighter_delta, priority_point_delta = deltas
    return InferenceObservation(
        player_id=score.ownerid,
        turn=turn.settings.turn,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=priority_point_delta,
        starbases_owned=score.starbases,
        is_after_ship_limit=is_after_ship_limit(turn, score),
        military_partition_slack_2x=military_partition_slack_2x,
        scoreboard_delta_source=scoreboard_delta_source,
    )


def observation_from_accelerated_segment(
    score: Score,
    turn: TurnInfo,
    segment: AcceleratedInferenceSegment,
) -> InferenceObservation:
    return observation_from_deltas(
        score,
        turn,
        (
            segment.military_delta_2x,
            segment.warship_delta,
            segment.freighter_delta,
            segment.priority_point_delta,
        ),
        scoreboard_delta_source="accelerated_segment",
    )


def accelerated_segment_for_host_turn(
    segments: tuple[AcceleratedInferenceSegment, ...],
    host_turn: int,
) -> AcceleratedInferenceSegment | None:
    for segment in segments:
        if segment.host_turn == host_turn:
            return segment
    return None


def load_accelerated_backfill_source_for_host_turn(
    score: Score,
    turn: TurnInfo,
    *,
    host_turn: int,
    load_scoreboard_turn: ScoreboardTurnLoader,
) -> AcceleratedBackfillSource | None:
    """Load accelerated segments from the first reliable scoreboard turn for backfill."""
    if not needs_accelerated_backfill(turn.settings.turn, turn.settings):
        return None

    scoreboard_turn_host = scoreboard_host_turn(turn.settings.turn)
    if scoreboard_turn_host is None or scoreboard_turn_host != host_turn:
        return None

    source_turn_number = first_reliable_accelerated_scoreboard_turn(turn.settings)
    if source_turn_number is None:
        return None

    source_turn = load_scoreboard_turn(source_turn_number)
    if source_turn is None:
        return None

    source_score = next(
        (row for row in source_turn.scores if row.ownerid == score.ownerid),
        None,
    )
    if source_score is None:
        return None

    segments = accelerated_inference_segments(source_score, source_turn)
    if segments is None:
        return None

    return AcceleratedBackfillSource(
        source_turn=source_turn,
        source_score=source_score,
        segments=segments,
        source_turn_number=source_turn_number,
    )


def resolve_inference_target_for_host_turn(
    score: Score,
    turn: TurnInfo,
    *,
    host_turn: int,
    load_scoreboard_turn: ScoreboardTurnLoader | None = None,
) -> ResolvedInferenceTarget | None:
    """Resolve catalog context for a host-turn target using inference-equivalent rules.

    Unreliable accelerated scoreboard rows backfill from the first reliable split;
    the first reliable row uses accelerated segments; later rows use score deltas.
    Returns None when accelerated context is required but cannot be loaded.
    """
    if needs_accelerated_backfill(turn.settings.turn, turn.settings):
        if load_scoreboard_turn is None:
            return None
        backfill_source = load_accelerated_backfill_source_for_host_turn(
            score,
            turn,
            host_turn=host_turn,
            load_scoreboard_turn=load_scoreboard_turn,
        )
        if backfill_source is None:
            return None
        segment = accelerated_segment_for_host_turn(backfill_source.segments, host_turn)
        if segment is None:
            return None
        return ResolvedInferenceTarget(
            observation=observation_from_accelerated_segment(
                backfill_source.source_score,
                backfill_source.source_turn,
                segment,
            ),
            turn_info=backfill_source.source_turn,
            score=backfill_source.source_score,
        )

    segments = accelerated_inference_segments(score, turn)
    if segments is not None:
        segment = accelerated_segment_for_host_turn(segments, host_turn)
        if segment is None:
            return None
        return ResolvedInferenceTarget(
            observation=observation_from_accelerated_segment(score, turn, segment),
            turn_info=turn,
            score=score,
        )

    expected_host_turn = scoreboard_host_turn(turn.settings.turn)
    if expected_host_turn is None or expected_host_turn != host_turn:
        return None
    prior_score = prior_scoreboard_row_score(score, turn, load_scoreboard_turn)
    military_delta_2x, warship_delta, freighter_delta, priority_point_delta, delta_source = (
        observation_deltas_from_score(score, turn, prior_score=prior_score)
    )
    return ResolvedInferenceTarget(
        observation=observation_from_deltas(
            score,
            turn,
            (military_delta_2x, warship_delta, freighter_delta, priority_point_delta),
            scoreboard_delta_source=delta_source,
        ),
        turn_info=turn,
        score=score,
    )
