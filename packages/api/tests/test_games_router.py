"""Tests for the /api/v1/games router."""

import json
from pathlib import Path

import pytest
from api.config import ApiConfig, set_config
from api.storage import clear_backend_cache, get_storage
from fastapi.testclient import TestClient

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _setup_storage():
    """Reset storage backend and seed with test data for each test.

    Explicitly sets include_dummy_data=False so tests don't depend on the
    lifespan seeding — data is injected directly into the backend here.
    """
    clear_backend_cache()
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        storage.put("games/628580/turns/111", json.load(f))
    yield
    clear_backend_cache()


@pytest.fixture
def client():
    from api.app import app

    return TestClient(app, raise_server_exceptions=False)


class TestGetGameInfo:
    def test_returns_200(self, client):
        resp = client.get("/v1/games/628580/info")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.get("/v1/games/628580/info")
        data = resp.json()
        assert "game" in data
        assert "players" in data
        assert "settings" in data
        assert data["game"]["id"] == 628580
        assert data["game"]["name"] == "Serada 9 Sector"

    def test_game_status_is_int(self, client):
        resp = client.get("/v1/games/628580/info")
        data = resp.json()
        assert isinstance(data["game"]["status"], int)

    def test_404_for_unknown_game(self, client):
        resp = client.get("/v1/games/999999/info")
        assert resp.status_code == 404


class TestGetTurnInfo:
    def test_returns_200(self, client):
        resp = client.get("/v1/games/628580/turns/111")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.get("/v1/games/628580/turns/111")
        data = resp.json()
        assert "settings" in data
        assert "game" in data
        assert "planets" in data
        assert "ships" in data
        assert data["settings"]["turn"] == 111

    def test_planets_list(self, client):
        resp = client.get("/v1/games/628580/turns/111")
        data = resp.json()
        assert isinstance(data["planets"], list)
        assert len(data["planets"]) > 0
        assert "id" in data["planets"][0]
        assert "name" in data["planets"][0]

    def test_ships_list(self, client):
        resp = client.get("/v1/games/628580/turns/111")
        data = resp.json()
        assert isinstance(data["ships"], list)
        assert len(data["ships"]) > 0

    def test_404_for_unknown_game(self, client):
        resp = client.get("/v1/games/999999/turns/111")
        assert resp.status_code == 404

    def test_404_for_unknown_turn(self, client):
        resp = client.get("/v1/games/628580/turns/999")
        assert resp.status_code == 404


class TestGetMapBase:
    def test_returns_200(self, client):
        resp = client.get("/v1/games/628580/turns/111/map-base")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.get("/v1/games/628580/turns/111/map-base")
        data = resp.json()
        assert data["analyticId"] == "base-map"
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)
        assert data["edges"] == []

    def test_404_for_unknown_turn(self, client):
        resp = client.get("/v1/games/628580/turns/999/map-base")
        assert resp.status_code == 404
