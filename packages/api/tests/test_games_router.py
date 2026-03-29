"""Tests for the /api/v1/games router."""

import copy
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
        storage.put("games/628580/1/turns/111", json.load(f))
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


class _FakePlanetsNu:
    """Minimal stub for POST /info refresh tests."""

    def __init__(self, load_payload: dict) -> None:
        self._load_payload = copy.deepcopy(load_payload)

    def login(self, username: str, password: str) -> str:
        return "fake-key"

    def load_game_info(self, game_id: int) -> dict:
        return copy.deepcopy(self._load_payload)

    def load_turn(self, *, game_id: int, turn: int, player_id: int, api_key: str | None = None):
        raise AssertionError("load_turn should not be called in this test")


class TestPostGameInfoRefresh:
    def test_401_when_no_stored_key_and_no_password(self, client):
        from api.app import app
        from api.routers.games import get_planets_client

        class _NeverCalled:
            def login(self, *args, **kwargs):
                raise AssertionError("login should not be called")

            def load_game_info(self, *args, **kwargs):
                raise AssertionError("load_game_info should not be called")

        app.dependency_overrides[get_planets_client] = lambda: _NeverCalled()
        try:
            resp = client.post(
                "/v1/games/628580/info",
                json={"operation": "refresh", "params": {"username": "player1"}},
            )
            assert resp.status_code == 401
            assert "credential" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_planets_client, None)

    def test_200_with_cached_api_key(self, client):
        from api.app import app
        from api.routers.games import get_planets_client

        storage = get_storage()
        storage.put("credentials/accounts/player1/api_key", "cached-key")
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            payload = json.load(f)
        app.dependency_overrides[get_planets_client] = lambda: _FakePlanetsNu(payload)
        try:
            resp = client.post(
                "/v1/games/628580/info",
                json={"operation": "refresh", "params": {"username": "player1"}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["game"]["id"] == 628580
        finally:
            app.dependency_overrides.pop(get_planets_client, None)


class TestGetTurnInfo:
    def test_returns_200(self, client):
        resp = client.get("/v1/games/628580/1/turns/111")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.get("/v1/games/628580/1/turns/111")
        data = resp.json()
        assert "settings" in data
        assert "game" in data
        assert "planets" in data
        assert "ships" in data
        assert data["settings"]["turn"] == 111

    def test_planets_list(self, client):
        resp = client.get("/v1/games/628580/1/turns/111")
        data = resp.json()
        assert isinstance(data["planets"], list)
        assert len(data["planets"]) > 0
        assert "id" in data["planets"][0]
        assert "name" in data["planets"][0]

    def test_ships_list(self, client):
        resp = client.get("/v1/games/628580/1/turns/111")
        data = resp.json()
        assert isinstance(data["ships"], list)
        assert len(data["ships"]) > 0

    def test_404_for_unknown_game(self, client):
        resp = client.get("/v1/games/999999/1/turns/111")
        assert resp.status_code == 404

    def test_404_for_unknown_turn(self, client):
        resp = client.get("/v1/games/628580/1/turns/999")
        assert resp.status_code == 404


class TestGetTurnAnalyticsBaseMap:
    def test_returns_200(self, client):
        resp = client.get("/v1/games/628580/1/turns/111/analytics/base-map")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.get("/v1/games/628580/1/turns/111/analytics/base-map")
        data = resp.json()
        assert data["analyticId"] == "base-map"
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)
        assert data["edges"] == []

    def test_404_for_unknown_turn(self, client):
        resp = client.get("/v1/games/628580/1/turns/999/analytics/base-map")
        assert resp.status_code == 404


class TestGetTurnAnalyticsConnections:
    def test_returns_routes(self, client):
        resp = client.get(
            "/v1/games/628580/1/turns/111/analytics/connections?warpSpeed=9"
            "&gravitonicMovement=false&flareMode=off"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["analyticId"] == "connections"
        assert data["nodes"] == []
        assert data["edges"] == []
        assert "routes" in data
        assert isinstance(data["routes"], list)
        for row in data["routes"]:
            assert "fromPlanetId" in row
            assert "toPlanetId" in row
            assert "viaFlare" in row
            assert row["fromPlanetId"] < row["toPlanetId"]


class _FakePlanetsNuEnsure(_FakePlanetsNu):
    def __init__(self, load_payload: dict, rst: dict) -> None:
        super().__init__(load_payload)
        self._rst = copy.deepcopy(rst)
        self.load_turn_calls: list[tuple[int, int, int]] = []

    def load_turn(self, *, game_id: int, turn: int, player_id: int, api_key: str | None = None):
        self.load_turn_calls.append((game_id, turn, player_id))
        return {"success": True, "rst": copy.deepcopy(self._rst)}


class TestPostEnsureTurn:
    def test_200_when_already_stored(self, client):
        from api.app import app
        from api.routers.games import get_planets_client

        app.dependency_overrides[get_planets_client] = lambda: _FakePlanetsNu({})
        try:
            storage = get_storage()
            storage.put("credentials/accounts/player1/api_key", "cached-key")
            resp = client.post(
                "/v1/games/628580/1/turns/111/ensure",
                json={"username": "player1"},
            )
            assert resp.status_code == 200
            assert resp.json()["settings"]["turn"] == 111
        finally:
            app.dependency_overrides.pop(get_planets_client, None)

    def test_loads_remote_when_missing(self, client):
        from api.app import app
        from api.routers.games import get_planets_client

        with open(ASSETS_DIR / "turn_sample.json") as f:
            rst = json.load(f)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        fake = _FakePlanetsNuEnsure(info, rst)
        app.dependency_overrides[get_planets_client] = lambda: fake
        try:
            storage = get_storage()
            storage.delete("games/628580/1/turns/111")
            storage.put("credentials/accounts/player1/api_key", "cached-key")
            resp = client.post(
                "/v1/games/628580/1/turns/111/ensure",
                json={"username": "player1"},
            )
            assert resp.status_code == 200
            assert fake.load_turn_calls == [(628580, 111, 1)]
            storage.get("games/628580/1/turns/111")
        finally:
            app.dependency_overrides.pop(get_planets_client, None)
