"""Tests for Fleet turn analytic registration shell."""

import json
from pathlib import Path

import pytest
from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.fleet import ANALYTIC_ID, get_fleet
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.registry import TURN_ANALYTICS
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        return turn_info_from_json(json.load(f))


def test_fleet_registered_in_turn_analytics():
    assert "fleet" in TURN_ANALYTICS


def test_fleet_compute_returns_scaffold_players_with_empty_records(sample_turn):
    data = get_fleet(sample_turn)
    assert data["analyticId"] == "fleet"
    players = data["players"]
    assert len(players) == 4
    assert players[0] == {
        "playerId": 8,
        "playerName": "koshling",
        "records": [],
    }
    for player in players:
        assert player["records"] == []
        assert isinstance(player["playerId"], int)
        assert isinstance(player["playerName"], str)


def test_registry_dispatches_fleet(sample_turn):
    services = build_ephemeral_fleet_compute_services(sample_turn)
    data = get_turn_analytic(
        "fleet",
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={ANALYTIC_ID: services},
    )
    assert data["analyticId"] == "fleet"
    assert len(data["players"]) == 4
    assert data["players"][0]["playerName"] == "koshling"
