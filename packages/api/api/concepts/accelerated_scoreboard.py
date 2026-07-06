"""Accelerated-start scoreboard helpers safe for compute-plane imports."""

from __future__ import annotations

from dataclasses import dataclass

from api.models.game import GameSettings, TurnInfo
from api.models.player import Score

HOMEBASE_STARBASE_DEFENSE_POSTS = 100
HOMEBASE_STARBASE_FIGHTERS = 20
HOMEBASE_PLANET_DEFENSE_POSTS = 20
HOMEBASE_STARTING_FREIGHTERS = 1
HOMEBASE_STARTING_FREIGHTER_HULL_ID = 16
HOMEBASE_STARTING_CAPITAL_SHIPS = 0
HOMEBASE_STARTING_STARBASES = 1

ACCEL_WINDOW_SEGMENT_ID = "accel_window"
REPORTED_HOST_TURN_SEGMENT_ID = "reported_host_turn"

STARBASE_FIGHTER_SCORE_DELTA_2X = 125
STARBASE_DEFENSE_POST_SCORE_DELTA_2X = 15
PLANET_DEFENSE_POST_SCORE_DELTA_2X = 11


@dataclass(frozen=True)
class ScoreboardSnapshot:
    militaryscore: int
    capitalships: int
    freighters: int
    starbases: int
    prioritypoints: int = 0


@dataclass(frozen=True)
class AcceleratedInferenceSegment:
    segment_id: str
    host_turn: int
    military_delta_2x: int
    warship_delta: int
    freighter_delta: int
    priority_point_delta: int


@dataclass(frozen=True)
class AcceleratedWindowShipBuilds:
    inferred_prior_to_reported_host_turn: ScoreboardSnapshot
    turn_one_baseline: ScoreboardSnapshot
    freighters_built_before_reported_host_turn: int
    warships_built_before_reported_host_turn: int
    freighters_built_on_reported_host_turn: int
    warships_built_on_reported_host_turn: int


def accelerated_turn_count(settings: GameSettings) -> int:
    return max(0, settings.acceleratedturns)


def is_first_reliable_scoreboard_turn(turn_number: int, settings: GameSettings) -> bool:
    accelerated = accelerated_turn_count(settings)
    return accelerated > 0 and turn_number == accelerated


def homeworld_baseline_military_2x(settings: GameSettings) -> int:
    if not settings.homeworldhasstarbase:
        return 0
    return (
        STARBASE_DEFENSE_POST_SCORE_DELTA_2X * HOMEBASE_STARBASE_DEFENSE_POSTS
        + STARBASE_FIGHTER_SCORE_DELTA_2X * HOMEBASE_STARBASE_FIGHTERS
        + PLANET_DEFENSE_POST_SCORE_DELTA_2X * HOMEBASE_PLANET_DEFENSE_POSTS
    )


def starting_scoreboard_snapshot(settings: GameSettings) -> ScoreboardSnapshot:
    if not settings.homeworldhasstarbase:
        return ScoreboardSnapshot(
            militaryscore=0,
            capitalships=HOMEBASE_STARTING_CAPITAL_SHIPS,
            freighters=0,
            starbases=0,
        )
    return ScoreboardSnapshot(
        militaryscore=homeworld_baseline_military_2x(settings) // 2,
        capitalships=HOMEBASE_STARTING_CAPITAL_SHIPS,
        freighters=HOMEBASE_STARTING_FREIGHTERS,
        starbases=HOMEBASE_STARTING_STARBASES,
    )


def cumulative_military_delta_2x(score: Score, settings: GameSettings) -> int:
    return 2 * score.militaryscore - homeworld_baseline_military_2x(settings)


def reported_host_military_delta_2x(score: Score) -> int:
    return 2 * score.militarychange


def accelerated_window_military_delta_2x(score: Score, turn: TurnInfo) -> int:
    if not is_first_reliable_scoreboard_turn(turn.settings.turn, turn.settings):
        return 0
    return cumulative_military_delta_2x(score, turn.settings) - reported_host_military_delta_2x(
        score
    )


def synthetic_scoreboard_before_reported_deltas(score: Score) -> ScoreboardSnapshot:
    return ScoreboardSnapshot(
        militaryscore=score.militaryscore - score.militarychange,
        capitalships=score.capitalships - score.shipchange,
        freighters=score.freighters - score.freighterchange,
        starbases=score.starbases - score.starbasechange,
        prioritypoints=score.prioritypoints - score.prioritypointchange,
    )


def infer_accelerated_window_ship_builds(
    score: Score,
    turn: TurnInfo,
) -> AcceleratedWindowShipBuilds | None:
    if not is_first_reliable_scoreboard_turn(turn.settings.turn, turn.settings):
        return None

    baseline = starting_scoreboard_snapshot(turn.settings)
    prior_to_reported_host_turn = synthetic_scoreboard_before_reported_deltas(score)
    return AcceleratedWindowShipBuilds(
        inferred_prior_to_reported_host_turn=prior_to_reported_host_turn,
        turn_one_baseline=baseline,
        freighters_built_before_reported_host_turn=max(
            0, prior_to_reported_host_turn.freighters - baseline.freighters
        ),
        warships_built_before_reported_host_turn=max(
            0, prior_to_reported_host_turn.capitalships - baseline.capitalships
        ),
        freighters_built_on_reported_host_turn=max(0, score.freighterchange),
        warships_built_on_reported_host_turn=max(0, score.shipchange),
    )


def accelerated_inference_segments(
    score: Score,
    turn: TurnInfo,
) -> tuple[AcceleratedInferenceSegment, ...] | None:
    if not is_first_reliable_scoreboard_turn(turn.settings.turn, turn.settings):
        return None

    builds = infer_accelerated_window_ship_builds(score, turn)
    if builds is None:
        return None

    reported_host_turn = turn.settings.turn - 1
    accel_host_turn = turn.settings.turn - 2
    segments: list[AcceleratedInferenceSegment] = []

    accel_segment = AcceleratedInferenceSegment(
        segment_id=ACCEL_WINDOW_SEGMENT_ID,
        host_turn=accel_host_turn,
        military_delta_2x=accelerated_window_military_delta_2x(score, turn),
        warship_delta=builds.warships_built_before_reported_host_turn,
        freighter_delta=builds.freighters_built_before_reported_host_turn,
        priority_point_delta=0,
    )
    if _segment_has_inference_targets(accel_segment):
        segments.append(accel_segment)

    segments.append(
        AcceleratedInferenceSegment(
            segment_id=REPORTED_HOST_TURN_SEGMENT_ID,
            host_turn=reported_host_turn,
            military_delta_2x=reported_host_military_delta_2x(score),
            warship_delta=score.shipchange,
            freighter_delta=score.freighterchange,
            priority_point_delta=score.prioritypointchange,
        )
    )
    return tuple(segments)


def _segment_has_inference_targets(segment: AcceleratedInferenceSegment) -> bool:
    return (
        segment.military_delta_2x != 0
        or segment.warship_delta != 0
        or segment.freighter_delta != 0
        or segment.priority_point_delta != 0
    )
