"""Scoreboard slice carried on fleet observation and materialization job wires.

The leg reads settings, roster id/username, and current-turn score rows. Planets,
ships, hulls, and messages stay off the wire. The slice is a local object inside
the leg and is never stored in the process ``TurnInfo`` cache.
"""

from __future__ import annotations

from typing import Any

from api.models.game import GameSettings, TurnInfo
from api.models.player import Player, Score

_SETTINGS_FIELDS = ("turn", "acceleratedturns", "homeworldhasstarbase")
_PLAYER_FIELDS = ("id", "username")
_SCORE_FIELDS = (
    "ownerid",
    "turn",
    "capitalships",
    "freighters",
    "shipchange",
    "freighterchange",
    "militaryscore",
    "militarychange",
    "starbases",
    "starbasechange",
    "prioritypoints",
    "prioritypointchange",
)


def fleet_scoreboard_slice_to_json(turn: TurnInfo) -> dict[str, Any]:
    """Copy the observation-leg scoreboard fields off a live ``TurnInfo``.

    Field reads only. Does not ``asdict`` or ``deepcopy`` the turn, its settings,
    its players, or its score rows.
    """
    shell_turn = turn.settings.turn
    return {
        "settings": {name: getattr(turn.settings, name) for name in _SETTINGS_FIELDS},
        "player": {name: getattr(turn.player, name) for name in _PLAYER_FIELDS},
        "players": [
            {name: getattr(player, name) for name in _PLAYER_FIELDS} for player in turn.players
        ],
        "scores": [
            {name: getattr(score, name) for name in _SCORE_FIELDS}
            for score in turn.scores
            if score.turn == shell_turn
        ],
    }


def turn_from_fleet_scoreboard_slice(turn_wire: dict[str, Any]) -> TurnInfo:
    """Build a local turn from a scoreboard slice. Does not touch ``TurnInfoCache``."""
    settings_wire = turn_wire["settings"]
    if not isinstance(settings_wire, dict):
        raise TypeError("fleet scoreboard slice settings must be an object")
    player_wire = turn_wire["player"]
    if not isinstance(player_wire, dict):
        raise TypeError("fleet scoreboard slice player must be an object")
    players_wire = turn_wire["players"]
    if not isinstance(players_wire, list):
        raise TypeError("fleet scoreboard slice players must be a list")
    scores_wire = turn_wire["scores"]
    if not isinstance(scores_wire, list):
        raise TypeError("fleet scoreboard slice scores must be a list")

    turn = _partial(
        TurnInfo,
        settings=_partial(GameSettings, **{name: settings_wire[name] for name in _SETTINGS_FIELDS}),
        player=_partial(Player, **{name: player_wire[name] for name in _PLAYER_FIELDS}),
        players=[
            _partial(Player, **{name: player[name] for name in _PLAYER_FIELDS})
            for player in players_wire
        ],
        scores=[
            _partial(Score, **{name: score[name] for name in _SCORE_FIELDS})
            for score in scores_wire
        ],
    )
    return turn


def _partial(cls: type, **attrs: object) -> Any:
    """Construct ``cls`` with only ``attrs`` set.

    Observation-leg readers touch the scoreboard fields. Unset RST fields raise
    ``AttributeError`` if a later change starts reading them from this object.
    """
    obj = object.__new__(cls)
    for name, value in attrs.items():
        setattr(obj, name, value)
    return obj
