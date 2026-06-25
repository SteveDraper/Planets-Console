"""Scoreboard ship-count aggregation for fleet analytics."""

from __future__ import annotations

from collections.abc import Iterator

from api.models.game import TurnInfo
from api.models.player import Score


def _current_turn_scores(turn: TurnInfo) -> Iterator[Score]:
    turn_number = turn.settings.turn
    for score in turn.scores:
        if score.turn == turn_number:
            yield score


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
    total = global_ship_count_from_scores(turn)
    if total is None:
        return None
    net = global_net_delta_from_scores(turn)
    builds = global_build_count_from_scores(turn)
    return total - net + builds
