"""Tests for the GameService."""

import copy
import json
from pathlib import Path

import pytest
from api.errors import (
    LoginCredentialsRequiredError,
    NotFoundError,
    UpstreamPlanetsError,
    ValidationError,
)
from api.models.game import GameInfo, TurnInfo
from api.models.game_info_operations import GameInfoUpdateOperation
from api.services.game_service import GameService
from api.storage.memory_asset import MemoryAssetBackend
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def seeded_backend():
    """Return a MemoryAssetBackend pre-seeded with the sample assets."""
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    return backend


@pytest.fixture
def service(seeded_backend):
    return GameService(seeded_backend)


class TestGetGameInfo:
    def test_returns_game_info(self, service):
        gi = service.get_game_info(628580)
        assert isinstance(gi, GameInfo)
        assert gi.game.id == 628580
        assert gi.game.name == "Serada 9 Sector"

    def test_player_id_for_perspective_from_game_info(self, service):
        gi = service.get_game_info(628580)
        pid = GameService._player_id_for_perspective_from_game_info(gi, 1, 628580)
        assert isinstance(pid, int)
        assert pid == gi.players[0].id

    def test_player_id_invalid_perspective_raises(self, service):
        gi = service.get_game_info(628580)
        with pytest.raises(ValidationError, match="Invalid perspective"):
            GameService._player_id_for_perspective_from_game_info(gi, 99999, 628580)

    def test_players_populated(self, service):
        gi = service.get_game_info(628580)
        assert len(gi.players) > 0
        assert gi.players[0].username

    def test_not_found_raises(self, service):
        with pytest.raises(NotFoundError):
            service.get_game_info(999999)


class TestGetTurnInfo:
    def test_returns_turn_info(self, service):
        ti = service.get_turn_info(628580, 1, 111)
        assert isinstance(ti, TurnInfo)
        assert ti.settings.turn == 111

    def test_planets_populated(self, service):
        ti = service.get_turn_info(628580, 1, 111)
        assert len(ti.planets) > 0

    def test_ships_populated(self, service):
        ti = service.get_turn_info(628580, 1, 111)
        assert len(ti.ships) > 0

    def test_not_found_game(self, service):
        with pytest.raises(NotFoundError):
            service.get_turn_info(999999, 1, 111)

    def test_not_found_turn(self, service):
        with pytest.raises(NotFoundError):
            service.get_turn_info(628580, 1, 999)


class TestGetPlanetFromTurn:
    def test_returns_planet_by_id(self, service):
        p = service.get_planet_from_turn(628580, 1, 111, 1)
        assert p.id == 1
        assert p.name == "Lorthidonia"

    def test_unknown_planet_id_raises(self, service):
        with pytest.raises(NotFoundError, match="No planet id"):
            service.get_planet_from_turn(628580, 1, 111, 999999999)


class TestMalformedStoreData:
    def test_game_info_non_dict_raises_validation(self):
        backend = MemoryAssetBackend(initial={})
        backend.put("games/1/info", ["not", "a", "dict"])
        svc = GameService(backend)
        with pytest.raises(ValidationError, match="Expected JSON object"):
            svc.get_game_info(1)

    def test_turn_info_non_dict_raises_validation(self):
        backend = MemoryAssetBackend(initial={})
        backend.put("games/1/1/turns/1", "just a string")
        svc = GameService(backend)
        with pytest.raises(ValidationError, match="Expected JSON object"):
            svc.get_turn_info(1, 1, 1)


class TestGetMapBase:
    def test_returns_planet_nodes(self, service):
        data = service.get_map_base(628580, 1, 111)
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

    def test_not_found_turn_raises(self, service):
        from api.errors import NotFoundError

        with pytest.raises(NotFoundError):
            service.get_map_base(628580, 1, 999)


class FakePlanetsNu:
    def __init__(self, load_payload: dict, *, login_returns: str = "fake-api-key") -> None:
        self._load_payload = load_payload
        self._login_returns = login_returns
        self.login_calls: list[tuple[str, str]] = []
        self.load_calls: list[int] = []
        self.load_turn_calls: list[tuple[int, int, int]] = []

    def login(self, username: str, password: str) -> str:
        self.login_calls.append((username, password))
        return self._login_returns

    def load_game_info(self, game_id: int) -> dict:
        self.load_calls.append(game_id)
        return copy.deepcopy(self._load_payload)

    def load_turn(self, *, game_id: int, turn: int, player_id: int, api_key: str | None = None):
        self.load_turn_calls.append((game_id, turn, player_id))
        raise AssertionError("load_turn must be overridden when used")


class TestRefreshGameInfo:
    @pytest.fixture
    def sample_info(self):
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            return json.load(f)

    def test_requires_password_when_no_stored_api_key(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        svc = GameService(backend)
        planets = FakePlanetsNu(sample_info)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1"},
        )
        with pytest.raises(LoginCredentialsRequiredError, match="Login credentials are required"):
            svc.update_game_info(628580, body, planets)
        assert planets.login_calls == []
        assert planets.load_calls == []

    def test_login_and_store_when_password_given(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        svc = GameService(backend)
        planets = FakePlanetsNu(sample_info, login_returns="stored-key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        gi = svc.update_game_info(628580, body, planets)
        assert planets.login_calls == [("player1", "secret")]
        assert planets.load_calls == [628580]
        assert backend.get("credentials/accounts/player1/api_key") == "stored-key"
        assert isinstance(gi, GameInfo)
        assert gi.game.id == 628580

    def test_skips_login_when_api_key_cached(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        backend.put("credentials/accounts/player1/api_key", "cached-key")
        svc = GameService(backend)
        planets = FakePlanetsNu(sample_info)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1"},
        )
        svc.update_game_info(628580, body, planets)
        assert planets.login_calls == []
        assert planets.load_calls == [628580]

    def test_wrong_game_id_from_host_raises(self, sample_info):
        bad = copy.deepcopy(sample_info)
        bad["game"]["id"] = 1
        backend = MemoryAssetBackend(initial={})
        svc = GameService(backend)
        planets = FakePlanetsNu(bad)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "x"},
        )
        with pytest.raises(ValidationError, match="does not match"):
            svc.update_game_info(628580, body, planets)

    def test_rejects_inconsistent_game_and_settings_turn(self, sample_info):
        bad = copy.deepcopy(sample_info)
        bad["settings"]["turn"] = 1
        backend = MemoryAssetBackend(initial={})
        svc = GameService(backend)
        planets = FakePlanetsNu(bad)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "x"},
        )
        with pytest.raises(ValidationError, match="inconsistent"):
            svc.update_game_info(628580, body, planets)


class FakePlanetsNuWithTurn(FakePlanetsNu):
    def __init__(self, load_payload: dict, rst_payload: dict, **kwargs) -> None:
        super().__init__(load_payload, **kwargs)
        self._rst = rst_payload

    def load_turn(self, *, game_id: int, turn: int, player_id: int, api_key: str | None = None):
        self.load_turn_calls.append((game_id, turn, player_id))
        return {"success": True, "rst": copy.deepcopy(self._rst)}


class TestEnsureTurnLoaded:
    @pytest.fixture
    def turn_rst(self):
        with open(ASSETS_DIR / "turn_sample.json") as f:
            return json.load(f)

    def test_returns_stored_turn_without_calling_planets(self, seeded_backend, turn_rst):
        svc = GameService(seeded_backend)
        planets = FakePlanetsNuWithTurn({}, turn_rst)
        params = RefreshGameInfoParams(username="player1", password="x")
        ti = svc.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert isinstance(ti, TurnInfo)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == []

    def test_allows_empty_username_when_turn_already_stored(self, seeded_backend, turn_rst):
        svc = GameService(seeded_backend)
        planets = FakePlanetsNuWithTurn({}, turn_rst)
        params = RefreshGameInfoParams(username="")
        ti = svc.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == []

    def test_fetches_and_stores_when_missing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        svc = GameService(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, turn_rst)
        backend.put("credentials/accounts/player1/api_key", "k")
        params = RefreshGameInfoParams(username="player1")
        ti = svc.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == [(628580, 111, 1)]
        backend.get("games/628580/1/turns/111")

    def test_rejects_mismatched_settings_turn_without_storing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        bad = copy.deepcopy(turn_rst)
        bad["settings"]["turn"] = 42
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, bad)
        backend.put("credentials/accounts/player1/api_key", "k")
        params = RefreshGameInfoParams(username="player1")
        svc = GameService(backend)
        with pytest.raises(UpstreamPlanetsError, match="settings.turn"):
            svc.ensure_turn_loaded(628580, 1, 111, params, planets)
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/111")

    def test_rejects_mismatched_game_id_without_storing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        bad = copy.deepcopy(turn_rst)
        bad["game"]["id"] = 999999
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, bad)
        backend.put("credentials/accounts/player1/api_key", "k")
        params = RefreshGameInfoParams(username="player1")
        svc = GameService(backend)
        with pytest.raises(UpstreamPlanetsError, match="game.id"):
            svc.ensure_turn_loaded(628580, 1, 111, params, planets)
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/111")

    def test_rejects_mismatched_game_turn_without_storing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        bad = copy.deepcopy(turn_rst)
        bad["game"]["turn"] = 42
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, bad)
        backend.put("credentials/accounts/player1/api_key", "k")
        params = RefreshGameInfoParams(username="player1")
        svc = GameService(backend)
        with pytest.raises(UpstreamPlanetsError, match="game.turn"):
            svc.ensure_turn_loaded(628580, 1, 111, params, planets)
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/111")

    def test_requires_password_when_no_key(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        svc = GameService(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, turn_rst)
        params = RefreshGameInfoParams(username="player1")
        with pytest.raises(LoginCredentialsRequiredError):
            svc.ensure_turn_loaded(628580, 1, 42, params, planets)
        assert planets.load_turn_calls == []

    def test_rejects_empty_username_when_turn_missing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        svc = GameService(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, turn_rst)
        params = RefreshGameInfoParams(username="")
        with pytest.raises(LoginCredentialsRequiredError, match="not already in storage"):
            svc.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert planets.load_turn_calls == []
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/111")
