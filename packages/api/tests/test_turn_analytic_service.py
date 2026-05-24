"""Tests for TurnAnalyticService."""

import json
from pathlib import Path

import pytest
from api.errors import NotFoundError
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def analytics_service():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    _, _, _, analytics = build_service_stack(backend)
    return analytics


class TestTurnAnalytics:
    def test_base_map_returns_planet_nodes(self, analytics_service):
        data = analytics_service.get_turn_analytics(628580, 1, 111, "base-map")
        assert data["analyticId"] == "base-map"
        assert isinstance(data["nodes"], list)
        assert len(data["nodes"]) > 0
        first = data["nodes"][0]
        assert first["id"].startswith("p")
        assert "x" in first and "y" in first
        assert "planet" in first
        assert isinstance(first["planet"], dict)
        assert first["planet"]["id"] == 1
        assert "ownerName" in first
        assert data["edges"] == []

    def test_base_map_not_found_turn_raises(self, analytics_service):
        with pytest.raises(NotFoundError):
            analytics_service.get_turn_analytics(628580, 1, 999, "base-map")

    def test_scores_returns_score_rows_with_current_values_and_changes(self, analytics_service):
        data = analytics_service.get_turn_analytics(628580, 1, 111, "scores")
        assert data["analyticId"] == "scores"
        assert len(data["rows"]) == 3
        first = data["rows"][0]
        assert first["playerId"] == 8
        assert first["racePlayer"] == "koshling"
        assert first["planets"] == {"value": 171, "change": -4}
        assert first["starbases"] == {"value": 121, "change": -2}
        assert first["warShips"] == {"value": 130, "change": 1}
        assert first["freighters"] == {"value": 26, "change": 0}
        assert first["military"] == {"value": 2509092, "change": -53869}
        assert first["priorityPoints"] == {"value": 217, "change": 54}
