"""Tests for Fleet turn analytic registration shell."""

import json
from pathlib import Path

from api.analytics.fleet import get_fleet
from api.analytics.registry import TURN_ANALYTICS
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def test_fleet_registered_in_turn_analytics():
    assert "fleet" in TURN_ANALYTICS


def test_fleet_compute_returns_scaffold_players_with_empty_records():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        turn = turn_info_from_json(json.load(f))

    data = get_fleet(turn)
    assert data["analyticId"] == "fleet"
    players = data["players"]
    assert len(players) == 4
    assert players[0] == {
        "playerId": players[0]["playerId"],
        "playerName": "koshling",
        "records": [],
    }
    for player in players:
        assert player["records"] == []
        assert isinstance(player["playerId"], int)
        assert isinstance(player["playerName"], str)
