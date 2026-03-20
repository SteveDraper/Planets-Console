"""Unit tests for BFF games list route."""

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.storage import clear_backend_cache, get_storage
from bff.app import app
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_storage():
    clear_backend_cache()
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    yield
    clear_backend_cache()


def test_list_games_empty_when_no_games_path():
    """GET /games returns empty list when store has no `games` node."""
    response = client.get("/games")
    assert response.status_code == 200
    assert response.json() == {"games": []}


def test_list_games_returns_child_ids():
    """GET /games returns shallow children of store path `games` as id objects."""
    storage = get_storage()
    storage.put("games/628580/info", {"stub": True})
    storage.put("games/999/turns/1", {"stub": True})
    response = client.get("/games")
    assert response.status_code == 200
    data = response.json()
    assert "games" in data
    ids = {g["id"] for g in data["games"]}
    assert ids == {"628580", "999"}
    for g in data["games"]:
        assert list(g.keys()) == ["id"]
