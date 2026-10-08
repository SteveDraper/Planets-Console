"""Accelerated-start scoreboard helpers safe for compute-plane imports.

Also owns the non-accelerated opening reveal: turn 2 when ``acceleratedturns``
is 0. That row's change columns are deltas from an empty turn 1 board, so
callers subtract the homeworld baseline from the totals.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.concepts.races import is_horwasp
from api.models.game import GameSettings, TurnInfo
from api.models.player import Score

HOMEBASE_STARBASE_DEFENSE_POSTS = 100
HOMEBASE_STARBASE_FIGHTERS = 20
HOMEBASE_PLANET_DEFENSE_POSTS = 20
HOMEBASE_STARTING_FREIGHTERS = 1
HOMEBASE_STARTING_FREIGHTER_HULL_ID = 16
# Nu starter MDSF mounts a Transwarp Drive (tech 10); host engine id is 9.
HOMEBASE_STARTING_FREIGHTER_ENGINE_ID = 9
HOMEBASE_STARTING_CAPITAL_SHIPS = 0
HOMEBASE_STARTING_STARBASES = 1
HOMEBASE_STARTING_PLANETS = 1

OPENING_BASELINE_DELTA_SOURCE = "opening_baseline"
REPORTED_CHANGE_FIELDS_DELTA_SOURCE = "reported_change_fields"

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
    planets: int
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
class ReportedScoreboardDeltas:
    """Per-row build deltas a score row reports for its host turn."""

    military_delta_2x: int
    warship_delta: int
    freighter_delta: int
    priority_point_delta: int
    planet_delta: int
    starbase_delta: int
    delta_source: str


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


def first_reliable_accelerated_scoreboard_turn(settings: GameSettings) -> int | None:
    """Scoreboard turn N when accelerated start is enabled; otherwise None."""
    accelerated = accelerated_turn_count(settings)
    return accelerated if accelerated > 0 else None


def accelerated_ensure_floor(settings: GameSettings, scope_turn: int) -> int:
    """Lowest turn ensure/fleet may require when targeting ``scope_turn``.

    Normal games and unreliable accelerated turns (``scope_turn < N``): turn 1.
    Once the target is at or above the first reliable scoreboard turn N, floor is
    N so missing/unreliable turns ``1..N-1`` are not required.

    Call sites compare directly: ``dep_turn < floor`` or ``turn == floor``.
    """
    accelerated = accelerated_turn_count(settings)
    if accelerated > 0 and scope_turn >= accelerated:
        return accelerated
    return 1


def is_unreliable_accelerated_scoreboard_turn(turn_number: int, settings: GameSettings) -> bool:
    accelerated = accelerated_turn_count(settings)
    return accelerated > 0 and 1 <= turn_number < accelerated


def is_first_reliable_scoreboard_turn(turn_number: int, settings: GameSettings) -> bool:
    accelerated = accelerated_turn_count(settings)
    return accelerated > 0 and turn_number == accelerated


def is_non_accelerated_opening_reveal(turn_number: int, settings: GameSettings) -> bool:
    """True on turn 2 of a game with no accelerated start.

    Turn 1 score rows are zeros. Turn 2 change columns equal the totals, so they
    include the homeworld. Later turns report a normal prior-row delta.
    """
    return accelerated_turn_count(settings) == 0 and turn_number == 2


HORWASP_STARTING_SNAPSHOT = ScoreboardSnapshot(
    militaryscore=0,
    capitalships=HOMEBASE_STARTING_CAPITAL_SHIPS,
    freighters=HOMEBASE_STARTING_FREIGHTERS,
    starbases=0,
    planets=HOMEBASE_STARTING_PLANETS,
)


def _opening_reveal_baseline(score: Score, turn: TurnInfo) -> ScoreboardSnapshot:
    """Homeworld baseline the score owner starts with.

    Horwasps start with the homeworld and starting freighter but no starbase and
    no planet defense posts.
    """
    for player in turn.players:
        if player.id == score.ownerid:
            if is_horwasp(player.raceid):
                return HORWASP_STARTING_SNAPSHOT
            return starting_scoreboard_snapshot(turn.settings)
    raise ValueError(
        f"Score owner {score.ownerid} is not in turn {turn.settings.turn} players; "
        "cannot choose the opening-reveal baseline"
    )


def reported_scoreboard_deltas(score: Score, turn: TurnInfo) -> ReportedScoreboardDeltas:
    """Build deltas this score row reports for its host turn.

    On the non-accelerated opening reveal the totals minus the owner's homeworld
    baseline; otherwise the row's change columns.
    """
    if is_non_accelerated_opening_reveal(turn.settings.turn, turn.settings):
        baseline = _opening_reveal_baseline(score, turn)
        return ReportedScoreboardDeltas(
            military_delta_2x=2 * (score.militaryscore - baseline.militaryscore),
            warship_delta=score.capitalships - baseline.capitalships,
            freighter_delta=score.freighters - baseline.freighters,
            priority_point_delta=score.prioritypoints - baseline.prioritypoints,
            planet_delta=score.planets - baseline.planets,
            starbase_delta=score.starbases - baseline.starbases,
            delta_source=OPENING_BASELINE_DELTA_SOURCE,
        )
    return ReportedScoreboardDeltas(
        military_delta_2x=reported_host_military_delta_2x(score),
        warship_delta=score.shipchange,
        freighter_delta=score.freighterchange,
        priority_point_delta=score.prioritypointchange,
        planet_delta=score.planetchange,
        starbase_delta=score.starbasechange,
        delta_source=REPORTED_CHANGE_FIELDS_DELTA_SOURCE,
    )


def homeworld_starting_inventory_counts(settings: GameSettings) -> tuple[int, int]:
    """(freighters, warships) on the settings homeworld snapshot.

    Ship-id bounds use this per-player count. It is 0 when the snapshot has
    no starting ships. Opening-reveal seed counts can differ by owner; those
    come from ``homeworld_seed_counts``.
    """
    baseline = starting_scoreboard_snapshot(settings)
    return baseline.freighters, baseline.capitalships


def homeworld_seed_counts(score: Score, turn: TurnInfo) -> tuple[int, int] | None:
    """Freighter and warship counts to seed, or None when this turn does not seed.

    Seed turns are the non-accelerated opening reveal and the first reliable
    accelerated scoreboard turn. The opening reveal uses the owner's baseline,
    so a Horwasp still has the starting freighter when the homeworld has no
    starbase. Accelerated seeding uses the settings snapshot.
    """
    turn_number = turn.settings.turn
    if is_non_accelerated_opening_reveal(turn_number, turn.settings):
        baseline = _opening_reveal_baseline(score, turn)
        return baseline.freighters, baseline.capitalships
    if is_first_reliable_scoreboard_turn(turn_number, turn.settings):
        return homeworld_starting_inventory_counts(turn.settings)
    return None


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
            planets=HOMEBASE_STARTING_PLANETS,
        )
    return ScoreboardSnapshot(
        militaryscore=homeworld_baseline_military_2x(settings) // 2,
        capitalships=HOMEBASE_STARTING_CAPITAL_SHIPS,
        freighters=HOMEBASE_STARTING_FREIGHTERS,
        starbases=HOMEBASE_STARTING_STARBASES,
        planets=HOMEBASE_STARTING_PLANETS,
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
        planets=score.planets - score.planetchange,
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
