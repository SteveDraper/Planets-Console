"""Scoreboard ship totals derived from TurnInfo score rows (compute-plane safe)."""

from __future__ import annotations

from collections.abc import Iterator

from api.models.game import TurnInfo
from api.models.player import Score


def iter_current_turn_scores(turn: TurnInfo) -> Iterator[Score]:
    """Yield scoreboard rows for the shell turn."""
    turn_number = turn.settings.turn
    for score in turn.scores:
        if score.turn == turn_number:
            yield score


def compute_max_ship_id_bound(turn: TurnInfo) -> int | None:
    """Upper-bound unknown ship ids from current-turn scoreboard totals and deltas.

    Returns None when the current turn has no scoreboard rows; callers must skip
    id-bound tightening rather than inferring from visible ship lists.
    """
    scores = list(iter_current_turn_scores(turn))
    if not scores:
        return None
    total = sum(score.capitalships + score.freighters for score in scores)
    net = sum(score.shipchange + score.freighterchange for score in scores)
    builds = sum(max(0, score.shipchange) + max(0, score.freighterchange) for score in scores)
    return total - net + builds
