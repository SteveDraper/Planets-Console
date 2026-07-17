"""Scoreboard reconstruction for games with accelerated start.

During accelerated start (``settings.acceleratedturns`` = N), scoreboard rows on
turns 1..N-1 are not filled in correctly. The first reliable score row is on
host turn N.

On turn N the row shows **current totals** and **deltas for host turn N-1 only**
(not cumulative over the accelerated window). Example (N=3, one starting
freighter): a freighter built on host turn 1 and a warship on host turn 2 appears
as ``Freighters 2 (+0)``, ``Military 1 (+1)`` -- the ``+0`` is relative to
inferred turn-2 totals (2 freighters already), while turn-1 freighter construction
is recovered by comparing inferred turn N-1 counts to the turn-1 baseline.

Build inference on the first reliable row runs **two separate solves**:

1. **Reported host turn** (N-1): ``militarychange`` / ``shipchange`` / ``freighterchange``
   on the turn N score row.
2. **Accelerated window** (host turns before N-1): military residual
   ``(militaryscore - baseline) - militarychange`` plus ship counts from
   ``infer_accelerated_window_ship_builds()``.
"""

from dataclasses import dataclass, replace

from api.analytics.military_score_inference.scoring import (
    planet_defense_post_score_delta_2x,
    starbase_defense_post_score_delta_2x,
    starbase_fighter_score_delta_2x,
)
from api.concepts.accelerated_scoreboard import (
    accelerated_turn_count,  # noqa: F401
    first_reliable_accelerated_scoreboard_turn,  # noqa: F401
    is_first_reliable_scoreboard_turn,
    is_unreliable_accelerated_scoreboard_turn,
)
from api.models.game import GameSettings, TurnInfo
from api.models.player import Score

# Standard Planets.nu homeworld starbase starting inventory when ``homeworldhasstarbase``.
HOMEBASE_STARBASE_DEFENSE_POSTS = 100
HOMEBASE_STARBASE_FIGHTERS = 20
HOMEBASE_PLANET_DEFENSE_POSTS = 20
HOMEBASE_STARTING_FREIGHTERS = 1
# Medium Deep Space Freighter (Planets.nu standard homeworld starting ship).
HOMEBASE_STARTING_FREIGHTER_HULL_ID = 16
HOMEBASE_STARTING_CAPITAL_SHIPS = 0
HOMEBASE_STARTING_STARBASES = 1
STANDARD_STARBASE_MAX_FIGHTERS = 60

# Scoreboard ``militarychange`` is stored in 1x integer units. Half-point military
# components (starbase fighters, defense posts) can lose up to one 2x unit when a host-turn
# delta is rounded or when an accelerated-start segment partition subtracts 1x values.
SCOREBOARD_MILITARY_PARTITION_SLACK_2X = 1

ACCEL_WINDOW_SEGMENT_ID = "accel_window"
REPORTED_HOST_TURN_SEGMENT_ID = "reported_host_turn"


@dataclass(frozen=True)
class ScoreboardSnapshot:
    """Scoreboard totals used as a synthetic prior reference."""

    militaryscore: int
    capitalships: int
    freighters: int
    starbases: int
    prioritypoints: int = 0


@dataclass(frozen=True)
class AcceleratedInferenceSegment:
    """One accelerated-start inference target (accel window or reported host turn)."""

    segment_id: str
    host_turn: int
    military_delta_2x: int
    warship_delta: int
    freighter_delta: int
    priority_point_delta: int

    @property
    def is_streaming_target(self) -> bool:
        """Whether live solution events apply to this segment (badge N = reported host turn)."""
        return self.segment_id == REPORTED_HOST_TURN_SEGMENT_ID


@dataclass(frozen=True)
class AcceleratedWindowShipBuilds:
    """Ship build counts inferred from the first reliable accelerated score row."""

    inferred_prior_to_reported_host_turn: ScoreboardSnapshot
    turn_one_baseline: ScoreboardSnapshot
    freighters_built_before_reported_host_turn: int
    warships_built_before_reported_host_turn: int
    freighters_built_on_reported_host_turn: int
    warships_built_on_reported_host_turn: int


def scoreboard_host_turn(scoreboard_turn: int) -> int | None:
    """Host turn whose delta is shown on a scoreboard row (row turn N shows host turn N-1)."""
    if scoreboard_turn <= 1:
        return None
    return scoreboard_turn - 1


def needs_accelerated_backfill(scoreboard_turn: int, settings: GameSettings) -> bool:
    """Whether this unreliable accelerated row should be filled from the first reliable split."""
    if not is_unreliable_accelerated_scoreboard_turn(scoreboard_turn, settings):
        return False
    return scoreboard_host_turn(scoreboard_turn) is not None


def homeworld_baseline_military_2x(settings: GameSettings) -> int:
    """Homeworld starting military score in 2x integer units (no per-component truncation)."""
    if not settings.homeworldhasstarbase:
        return 0
    return (
        starbase_defense_post_score_delta_2x(HOMEBASE_STARBASE_DEFENSE_POSTS)
        + starbase_fighter_score_delta_2x(HOMEBASE_STARBASE_FIGHTERS)
        + planet_defense_post_score_delta_2x(HOMEBASE_PLANET_DEFENSE_POSTS)
    )


def starting_scoreboard_snapshot(settings: GameSettings) -> ScoreboardSnapshot:
    """Homeworld baseline totals at game start (turn 1) under normal Starmap settings."""
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
    """Military score gained since homeworld baseline, in 2x integer units."""
    return 2 * score.militaryscore - homeworld_baseline_military_2x(settings)


def reported_host_military_delta_2x(score: Score) -> int:
    """Reported host-turn military delta on a scoreboard row, in 2x integer units."""
    return 2 * score.militarychange


def accelerated_window_military_delta_2x(score: Score, turn: TurnInfo) -> int:
    """Military score increase in the accelerated window before the reported host turn (2x)."""
    if not is_first_reliable_scoreboard_turn(turn.settings.turn, turn.settings):
        return 0
    return cumulative_military_delta_2x(score, turn.settings) - reported_host_military_delta_2x(
        score
    )


def synthetic_scoreboard_before_reported_deltas(score: Score) -> ScoreboardSnapshot:
    """Infer scoreboard totals at host turn N-1 from turn N current values and deltas."""
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
    """Split ship builds across the accelerated window vs the reported host turn.

    Only defined on the first reliable scoreboard turn (``turn == acceleratedturns``).
    """
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


def effective_prior_score_row(
    *,
    score_at_reliable_turn: Score,
    turn_at_reliable_turn: TurnInfo,
) -> Score:
    """Synthetic host-turn N-1 row derived from the first reliable scoreboard turn N."""
    snapshot = synthetic_scoreboard_before_reported_deltas(score_at_reliable_turn)
    return _apply_snapshot(score_at_reliable_turn, snapshot)


def _reported_scoreboard_changes_are_zero(score: Score) -> bool:
    return (
        score.militarychange == 0
        and score.shipchange == 0
        and score.freighterchange == 0
        and score.prioritypointchange == 0
    )


def scoreboard_row_deltas_from_prior_totals(
    score: Score,
    prior_score: Score,
) -> tuple[int, int, int, int]:
    """Infer per-row deltas when change columns are missing (e.g. spectator loads)."""
    return (
        2 * (score.militaryscore - prior_score.militaryscore),
        score.capitalships - prior_score.capitalships,
        score.freighters - prior_score.freighters,
        score.prioritypoints - prior_score.prioritypoints,
    )


def observation_deltas_from_score(
    score: Score,
    turn: TurnInfo,
    *,
    prior_score: Score | None = None,
) -> tuple[int, int, int, int, str]:
    """Return scoreboard-row deltas for the reported host turn on this row."""
    del turn
    reported = (
        reported_host_military_delta_2x(score),
        score.shipchange,
        score.freighterchange,
        score.prioritypointchange,
    )
    if not _reported_scoreboard_changes_are_zero(score) or prior_score is None:
        return (*reported, "reported_change_fields")
    from_totals = scoreboard_row_deltas_from_prior_totals(score, prior_score)
    if from_totals == (0, 0, 0, 0):
        return (*reported, "reported_change_fields")
    return (*from_totals, "prior_row_total_diff")


def accelerated_window_military_change(score: Score, turn: TurnInfo) -> int:
    """Military score increase in the accelerated window before the reported host turn (1x)."""
    return accelerated_window_military_delta_2x(score, turn) // 2


def accelerated_inference_segments(
    score: Score,
    turn: TurnInfo,
) -> tuple[AcceleratedInferenceSegment, ...] | None:
    """Split first reliable accelerated row into accel-window and reported-host-turn targets."""
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


def _apply_snapshot(score: Score, snapshot: ScoreboardSnapshot) -> Score:
    return replace(
        score,
        militaryscore=snapshot.militaryscore,
        capitalships=snapshot.capitalships,
        freighters=snapshot.freighters,
        starbases=snapshot.starbases,
        prioritypoints=snapshot.prioritypoints,
        militarychange=0,
        shipchange=0,
        freighterchange=0,
        starbasechange=0,
        prioritypointchange=0,
        inventorychange=0,
        planetchange=0,
    )
