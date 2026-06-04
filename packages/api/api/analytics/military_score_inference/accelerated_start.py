"""Scoreboard reconstruction for games with accelerated start.

During accelerated start (``settings.acceleratedturns`` = N), scoreboard rows on
turns 1..N-1 are not filled in correctly. The first reliable score row is on
host turn N. Inference on that turn explains activity since game start, so the
effective prior military total is the standard homeworld starting score, not the
zeroed prior-turn row.

On turn N the row shows **current totals** and **deltas for host turn N-1 only**
(not cumulative over the accelerated window). Example (N=3, one starting
freighter): a freighter built on host turn 1 and a warship on host turn 2 appears
as ``Freighters 2 (+0)``, ``Military 1 (+1)`` -- the ``+0`` is relative to
inferred turn-2 totals (2 freighters already), while turn-1 freighter construction
is recovered by comparing inferred turn N-1 counts to the turn-1 baseline.
"""

from dataclasses import dataclass, replace

from api.analytics.military_score_inference.scoring import (
    planet_defense_post_score_delta_2x,
    starbase_defense_post_score_delta_2x,
    starbase_fighter_score_delta_2x,
)
from api.models.game import GameSettings, TurnInfo
from api.models.player import Score

# Standard Planets.nu homeworld starbase starting inventory when ``homeworldhasstarbase``.
HOMEBASE_STARBASE_DEFENSE_POSTS = 100
HOMEBASE_STARBASE_FIGHTERS = 20
HOMEBASE_PLANET_DEFENSE_POSTS = 20
HOMEBASE_STARTING_FREIGHTERS = 1
HOMEBASE_STARTING_CAPITAL_SHIPS = 0
HOMEBASE_STARTING_STARBASES = 1
STANDARD_STARBASE_MAX_FIGHTERS = 60


@dataclass(frozen=True)
class ScoreboardSnapshot:
    """Scoreboard totals used as a synthetic prior reference."""

    militaryscore: int
    capitalships: int
    freighters: int
    starbases: int
    prioritypoints: int = 0


@dataclass(frozen=True)
class AcceleratedWindowShipBuilds:
    """Ship build counts inferred from the first reliable accelerated score row."""

    inferred_prior_to_reported_host_turn: ScoreboardSnapshot
    turn_one_baseline: ScoreboardSnapshot
    freighters_built_before_reported_host_turn: int
    warships_built_before_reported_host_turn: int
    freighters_built_on_reported_host_turn: int
    warships_built_on_reported_host_turn: int


def accelerated_turn_count(settings: GameSettings) -> int:
    """Return N when accelerated start is enabled, else 0."""
    return max(0, settings.acceleratedturns)


def is_unreliable_accelerated_scoreboard_turn(turn_number: int, settings: GameSettings) -> bool:
    """Return whether persisted scoreboard rows omit reliable totals on this turn."""
    accelerated = accelerated_turn_count(settings)
    return accelerated > 0 and 1 <= turn_number < accelerated


def is_first_reliable_scoreboard_turn(turn_number: int, settings: GameSettings) -> bool:
    """Return whether this is the first host turn with a filled-in scoreboard row."""
    accelerated = accelerated_turn_count(settings)
    return accelerated > 0 and turn_number == accelerated


def starting_scoreboard_snapshot(settings: GameSettings) -> ScoreboardSnapshot:
    """Homeworld baseline totals at game start (turn 1) under normal Starmap settings."""
    if not settings.homeworldhasstarbase:
        return ScoreboardSnapshot(
            militaryscore=0,
            capitalships=HOMEBASE_STARTING_CAPITAL_SHIPS,
            freighters=0,
            starbases=0,
        )

    militaryscore = (
        starbase_defense_post_score_delta_2x(HOMEBASE_STARBASE_DEFENSE_POSTS) // 2
        + starbase_fighter_score_delta_2x(HOMEBASE_STARBASE_FIGHTERS) // 2
        + planet_defense_post_score_delta_2x(HOMEBASE_PLANET_DEFENSE_POSTS) // 2
    )
    return ScoreboardSnapshot(
        militaryscore=militaryscore,
        capitalships=HOMEBASE_STARTING_CAPITAL_SHIPS,
        freighters=HOMEBASE_STARTING_FREIGHTERS,
        starbases=HOMEBASE_STARTING_STARBASES,
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


def observation_deltas_from_score(
    score: Score,
    turn: TurnInfo,
) -> tuple[int, int, int, int]:
    """Return (military_delta_2x, warship_delta, freighter_delta, priority_point_delta)."""
    settings = turn.settings
    turn_number = settings.turn
    if is_first_reliable_scoreboard_turn(turn_number, settings):
        baseline = starting_scoreboard_snapshot(settings)
        military_change = score.militaryscore - baseline.militaryscore
        # Warships since turn-1 baseline; ``shipchange`` is only host turn N-1.
        warship_delta = score.capitalships - baseline.capitalships
        # Freighters do not affect military score; keep scoreboard freighterchange
        # (host N-1 only). Use infer_accelerated_window_ship_builds() for accel-window
        # freighter construction inferred from totals vs baseline.
        freighter_delta = score.freighterchange
        return (
            2 * military_change,
            warship_delta,
            freighter_delta,
            score.prioritypointchange,
        )
    return (
        2 * score.militarychange,
        score.shipchange,
        score.freighterchange,
        score.prioritypointchange,
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
