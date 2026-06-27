"""Scoreboard ship-count aggregation for fleet analytics."""

from __future__ import annotations

from collections.abc import Iterator

from api.analytics.scores.scoreboard_placeholder_targets import homeworld_starting_inventory_counts
from api.analytics.turn_roster import iter_turn_players
from api.models.game import TurnInfo
from api.models.player import Score


def iter_current_turn_scores(turn: TurnInfo) -> Iterator[Score]:
    """Yield scoreboard rows for the shell turn."""
    turn_number = turn.settings.turn
    for score in turn.scores:
        if score.turn == turn_number:
            yield score


def _current_turn_scores(turn: TurnInfo) -> Iterator[Score]:
    return iter_current_turn_scores(turn)


def global_ship_count_from_scores(turn: TurnInfo) -> int | None:
    """Sum scoreboard ship totals for the turn, when score rows exist."""
    scores = list(_current_turn_scores(turn))
    if not scores:
        return None
    return sum(score.capitalships + score.freighters for score in scores)


def global_build_count_from_scores(turn: TurnInfo) -> int:
    """Sum positive warship and freighter builds reported on the turn."""
    total = 0
    for score in _current_turn_scores(turn):
        if score.shipchange > 0:
            total += score.shipchange
        if score.freighterchange > 0:
            total += score.freighterchange
    return total


def global_net_delta_from_scores(turn: TurnInfo) -> int:
    """Sum signed warship and freighter scoreboard deltas for the turn."""
    return sum(score.shipchange + score.freighterchange for score in _current_turn_scores(turn))


def compute_max_ship_id_bound(turn: TurnInfo) -> int | None:
    """Upper-bound unknown ship ids from current-turn scoreboard totals and deltas.

    Returns None when the current turn has no scoreboard rows; callers must skip
    id-bound tightening rather than inferring from visible ship lists.
    """
    scores = list(_current_turn_scores(turn))
    if not scores:
        return None
    return _max_ship_id_bound_from_scores(scores)


def _max_ship_id_bound_from_scores(scores: list[Score]) -> int:
    total = sum(score.capitalships + score.freighters for score in scores)
    net = sum(score.shipchange + score.freighterchange for score in scores)
    builds = sum(max(0, score.shipchange) + max(0, score.freighterchange) for score in scores)
    return total - net + builds


def global_ship_count_from_score_rows(scores: list[Score]) -> int:
    """Sum scoreboard ship totals across score rows."""
    return sum(score.capitalships + score.freighters for score in scores)


def global_ship_count_at_synthetic_prior(turn: TurnInfo) -> int | None:
    """Global ship total at host turn N-1 inferred from first reliable accelerated row N."""
    scores = list(_current_turn_scores(turn))
    if not scores:
        return None
    return sum(
        score.capitalships - score.shipchange + score.freighters - score.freighterchange
        for score in scores
    )


def global_homeworld_starting_ship_id_bound(turn: TurnInfo) -> int:
    """Upper bound on ids after each player receives homeworld starting ships."""
    freighters, warships = homeworld_starting_inventory_counts(turn)
    per_player = warships + freighters
    if per_player <= 0:
        return 0
    return per_player * len(list(iter_turn_players(turn)))


def _is_first_reliable_accelerated_shell_turn(shell_turn: int, turn: TurnInfo) -> bool:
    accelerated = max(0, turn.settings.acceleratedturns)
    return accelerated > 0 and shell_turn == accelerated


def max_ship_id_bound_for_inferred_record(
    turn: TurnInfo,
    *,
    shell_turn: int,
    built_turn: int | None,
    is_starting_inventory: bool,
) -> int | None:
    """Resolve the id upper bound for one inferred placeholder on this shell turn."""
    if is_starting_inventory:
        bound = global_homeworld_starting_ship_id_bound(turn)
        return bound if bound > 0 else None

    if (
        _is_first_reliable_accelerated_shell_turn(shell_turn, turn)
        and built_turn is not None
        and built_turn < shell_turn - 1
    ):
        return global_ship_count_at_synthetic_prior(turn)

    return compute_max_ship_id_bound(turn)
