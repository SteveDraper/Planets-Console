"""Tests for player elimination helpers (628580-verified semantics)."""

from api.models.enums import PlayerStatus
from api.models.player import Player
from api.services.player_elimination import (
    elimination_turn,
    is_eliminated_at_turn,
    last_meaningful_turn,
    player_status,
)


def _player(**overrides: object) -> Player:
    base = {
        "id": 1,
        "status": 1,
        "statusturn": 1,
        "accountid": 159409,
        "username": "dougp314",
        "email": "",
        "raceid": 1,
        "teamid": 0,
        "prioritypoints": 0,
        "joinrank": 0,
        "finishrank": 0,
        "turnjoined": 1,
        "turnready": False,
        "turnreadydate": "",
        "turnstatus": 1,
        "turnsmissed": 0,
        "turnsmissedtotal": 0,
        "turnsholiday": 0,
        "turnsearly": 0,
        "turn": 3,
        "timcontinuum": 0,
        "savekey": "",
        "tutorialid": 0,
        "tutorialtaskid": 0,
        "megacredits": 0,
        "duranium": 0,
        "tritanium": 0,
        "molybdenum": 0,
        "leagueteamid": 0,
        "activehulls": "",
        "activeadvantages": "",
        "activeengines": "",
        "activebeams": "",
        "activetorps": "",
    }
    base.update(overrides)
    return Player(**base)


def test_eliminated_player_628580_perspective_1() -> None:
    """Live API: dead at turn 49; alive at 48."""
    eliminated = _player(status=3, statusturn=49, username="dead", accountid=0)
    assert player_status(eliminated) == PlayerStatus.ELIMINATED
    assert elimination_turn(eliminated) == 49
    assert not is_eliminated_at_turn(eliminated, 48)
    assert is_eliminated_at_turn(eliminated, 49)
    assert is_eliminated_at_turn(eliminated, 111)
    assert last_meaningful_turn(eliminated, 111) == 49


def test_active_player_not_eliminated() -> None:
    active = _player(status=1, statusturn=1)
    assert player_status(active) == PlayerStatus.ACTIVE
    assert elimination_turn(active) is None
    assert not is_eliminated_at_turn(active, 111)
    assert last_meaningful_turn(active, 111) == 111


def test_statusturn_without_elimination_628580_nocere() -> None:
    """Live API: nocere has status=1, statusturn=90 (slot join, not death)."""
    joined = _player(id=11, status=1, statusturn=90, username="nocere", accountid=34824)
    assert elimination_turn(joined) is None
    assert not is_eliminated_at_turn(joined, 90)
    assert last_meaningful_turn(joined, 111) == 111


def test_unknown_status_is_not_eliminated() -> None:
    unknown = _player(status=99, statusturn=10)
    assert player_status(unknown) == PlayerStatus.UNKNOWN
    assert elimination_turn(unknown) is None
