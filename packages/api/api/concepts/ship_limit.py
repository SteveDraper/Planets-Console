"""Shared ship-limit helpers from scoreboard ship counts."""

from __future__ import annotations

from collections.abc import Sequence

from api.models.game import GameSettings
from api.models.player import Score


def reported_ships_for_score(score: Score) -> int:
    """Capital + freighter count from one scoreboard row."""
    return score.capitalships + score.freighters


def total_reported_ships(scores: Sequence[Score]) -> int:
    """Sum of reported ships across the given scoreboard rows."""
    return sum(reported_ships_for_score(score) for score in scores)


def is_at_or_over_shared_ship_limit(settings: GameSettings, scores: Sequence[Score]) -> bool:
    """True when galaxy scoreboard ship total is at/over ``settings.shiplimit``.

    Only rows with ``score.turn == settings.turn`` count. Callers may pass a full
    ``TurnInfo.scores`` list; earlier-turn rows are ignored.

    Used as a game-maturity gate (e.g. homeworld soft origin-distance freeze).
    Independent of PLS per-player caps (``shiplimittype != 0``).
    """
    current_turn = settings.turn
    current_scores = tuple(score for score in scores if score.turn == current_turn)
    return total_reported_ships(current_scores) >= settings.shiplimit
