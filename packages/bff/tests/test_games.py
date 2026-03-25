"""Unit tests for BFF games list route."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.services.store_service import StoreService
from api.storage import clear_backend_cache, get_storage
from bff.app import app
from bff.routers import games as games_router
from fastapi.testclient import TestClient

client = TestClient(app)

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "api" / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _reset_storage():
    clear_backend_cache()
    games_router._sector_title_by_stored_game_id.clear()
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
    storage.put("games/999/1/turns/1", {"stub": True})
    response = client.get("/games")
    assert response.status_code == 200
    data = response.json()
    assert "games" in data
    ids = {g["id"] for g in data["games"]}
    assert ids == {"628580", "999"}
    for g in data["games"]:
        assert "id" in g
        assert set(g.keys()) <= {"id", "sectorName"}


def test_list_games_includes_sector_name_when_cached_info_has_title():
    """Each game may include sectorName from stored `games/{id}/info` when present."""
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    response = client.get("/games")
    assert response.status_code == 200
    games = response.json()["games"]
    hit = next(g for g in games if g["id"] == "628580")
    assert hit.get("sectorName") == "Serada 9 Sector"


def test_list_games_does_not_re_read_info_when_sector_titles_are_cached():
    """Second list uses the in-process sector title cache (no N store reads per game)."""
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        payload = json.load(f)
    storage.put("games/111/info", payload)
    storage.put("games/222/info", payload)

    info_reads: list[str] = []
    original_read = StoreService.read

    def counting_read(self, path: str) -> object:
        if path.startswith("games/") and path.endswith("/info"):
            info_reads.append(path)
        return original_read(self, path)

    with patch.object(StoreService, "read", counting_read):
        r1 = client.get("/games")
        r2 = client.get("/games")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert info_reads == ["games/111/info", "games/222/info"]


@patch("bff.routers.games.PlanetsNuClient")
def test_post_game_info_refresh_with_cached_key(mock_pc_class):
    """POST /games/{id}/info delegates to Core refresh; Planets client is used for loadinfo."""
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        sample = json.load(f)
    mock_instance = mock_pc_class.from_config.return_value
    mock_instance.load_game_info.return_value = sample

    storage = get_storage()
    storage.put("credentials/accounts/player1/api_key", "cached-key")

    response = client.post(
        "/games/628580/info",
        json={"operation": "refresh", "params": {"username": "player1"}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["game"]["id"] == 628580
    mock_instance.load_game_info.assert_called_once_with(628580)
    mock_instance.login.assert_not_called()


@patch("bff.routers.games.PlanetsNuClient")
def test_post_game_info_refresh_401_without_credentials(mock_pc_class):
    mock_pc_class.from_config.return_value = object()
    response = client.post(
        "/games/628580/info",
        json={"operation": "refresh", "params": {"username": "nobody"}},
    )
    assert response.status_code == 401


@patch("bff.routers.games.PlanetsNuClient")
def test_post_turns_ensure_uses_loadturn_when_missing(mock_pc_class):
    with open(ASSETS_DIR / "turn_sample.json") as f:
        rst = json.load(f)
    mock_instance = mock_pc_class.from_config.return_value
    mock_instance.load_turn.return_value = {"success": True, "rst": rst}

    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    storage.put("credentials/accounts/player1/api_key", "cached-key")

    response = client.post(
        "/games/628580/turns/ensure",
        json={
            "turn": 111,
            "perspective": 1,
            "username": "player1",
        },
    )
    assert response.status_code == 200
    mock_instance.load_turn.assert_called_once()
    _, kwargs = mock_instance.load_turn.call_args
    assert kwargs["game_id"] == 628580
    assert kwargs["turn"] == 111
    assert kwargs["player_id"] == 1
    storage.get("games/628580/1/turns/111")


@patch("bff.routers.games.PlanetsNuClient")
def test_post_turns_ensure_skips_planets_when_present(mock_pc_class):
    mock_instance = mock_pc_class.from_config.return_value
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        storage.put("games/628580/1/turns/111", json.load(f))
    storage.put("credentials/accounts/player1/api_key", "cached-key")

    response = client.post(
        "/games/628580/turns/ensure",
        json={
            "turn": 111,
            "perspective": 1,
            "username": "player1",
        },
    )
    assert response.status_code == 200
    mock_instance.load_turn.assert_not_called()


def test_post_warp_well_coordinate_in_well_matches_core():
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        storage.put("games/628580/1/turns/111", json.load(f))

    response = client.post(
        "/games/628580/1/turns/111/concepts/warp-wells/coordinate-in-well",
        json={
            "planet_id": 1,
            "map_x": 2078,
            "map_y": 1149,
            "well_type": "normal",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"inside": True}


def test_get_warp_well_cells_matches_core():
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        storage.put("games/628580/1/turns/111", json.load(f))

    response = client.get(
        "/games/628580/1/turns/111/concepts/warp-wells/cells",
        params={"planet_id": 1, "well_type": "normal"},
    )
    assert response.status_code == 200
    data = response.json()
    assert {"x": 2078, "y": 1149} in data["cells"]
