"""Tests for turn roster helpers."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.turn_roster import iter_turn_players, player_by_id, players_by_id
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        return turn_info_from_json(json.load(f))


def test_iter_turn_players_yields_perspective_first(sample_turn):
    players = list(iter_turn_players(sample_turn))
    assert players[0].id == sample_turn.player.id
    assert players[0].username == sample_turn.player.username


def test_iter_turn_players_dedupes_by_id_perspective_wins(sample_turn):
    duplicate_in_roster = replace(sample_turn.player, username="from-roster")
    turn = replace(sample_turn, players=[*sample_turn.players, duplicate_in_roster])
    players = list(iter_turn_players(turn))
    assert len(players) == 4
    assert players[0].username == sample_turn.player.username
    assert all(player.username != "from-roster" for player in players)


def test_players_by_id_dedupes_perspective_record(sample_turn):
    duplicate_in_roster = replace(sample_turn.player, username="from-roster")
    turn = replace(sample_turn, players=[*sample_turn.players, duplicate_in_roster])
    roster = players_by_id(turn)
    assert roster[sample_turn.player.id].username == sample_turn.player.username


def test_player_by_id_raises_for_unknown_id(sample_turn):
    with pytest.raises(ValueError, match="unknown player id"):
        player_by_id(sample_turn, -1)
