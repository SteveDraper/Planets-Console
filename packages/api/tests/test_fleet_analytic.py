"""Tests for Fleet turn analytic registration shell."""

from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.fleet import ANALYTIC_ID, get_fleet
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.registry import TURN_ANALYTICS


def test_fleet_registered_in_turn_analytics():
    assert "fleet" in TURN_ANALYTICS


def test_fleet_compute_returns_players_with_observed_records(sample_turn):
    data = get_fleet(sample_turn)
    assert data["analyticId"] == "fleet"
    players = data["players"]
    assert len(players) == 4
    koshling = next(player for player in players if player["playerId"] == 8)
    assert len(koshling["records"]) == 5
    assert koshling["records"][0]["events"][0]["kind"] == "sighting"
    for player in players:
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
