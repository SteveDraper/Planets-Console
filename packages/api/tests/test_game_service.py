"""Tests for the GameService."""

import copy
import json
from pathlib import Path

import pytest
from api.errors import LoginCredentialsRequiredError, NotFoundError, ValidationError
from api.models.game import GameInfo
from api.models.game_info_operations import GameInfoUpdateOperation
from api.services.game_service import GameService
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend
from api.transport.game_info_update import GameInfoUpdateRequest

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def game_info_sample_data():
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        return json.load(f)


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
    games, _, _, _, _ = build_service_stack(seeded_backend)
    return games


class TestGetGameInfo:
    def test_returns_game_info(self, service):
        gi = service.get_game_info(628580)
        assert isinstance(gi, GameInfo)
        assert gi.game.id == 628580
        assert gi.game.name == "Serada 9 Sector"

    def test_player_id_for_perspective(self, service):
        gi = service.get_game_info(628580)
        pid = GameService.player_id_for_perspective(gi, 1, 628580)
        assert isinstance(pid, int)
        assert pid == gi.players[0].id

    def test_player_id_for_pseudo_perspective_zero(self, service):
        gi = service.get_game_info(628580)
        assert GameService.player_id_for_perspective(gi, 0, 628580) == 0

    def test_player_id_invalid_perspective_raises(self, service):
        gi = service.get_game_info(628580)
        with pytest.raises(ValidationError, match="Invalid perspective"):
            GameService.player_id_for_perspective(gi, 99999, 628580)

    def test_players_populated(self, service):
        gi = service.get_game_info(628580)
        assert len(gi.players) > 0
        assert gi.players[0].username

    def test_not_found_raises(self, service):
        with pytest.raises(NotFoundError):
            service.get_game_info(999999)


class TestMalformedGameInfoStoreData:
    def test_game_info_non_dict_raises_validation(self):
        backend = MemoryAssetBackend(initial={})
        backend.put("games/1/info", ["not", "a", "dict"])
        games, _, _, _, _ = build_service_stack(backend)
        with pytest.raises(ValidationError, match="Expected JSON object"):
            games.get_game_info(1)

    def test_game_info_shape_error_includes_field_detail(self, game_info_sample_data):
        backend = MemoryAssetBackend(initial={})
        bad = copy.deepcopy(game_info_sample_data)
        del bad["settings"]["id"]
        backend.put("games/628580/info", bad)
        games, _, _, _, _ = build_service_stack(backend)
        with pytest.raises(ValidationError, match="settings\\.id"):
            games.get_game_info(628580)


class FakePlanetsNu:
    def __init__(self, load_payload: dict, *, login_returns: str = "fake-api-key") -> None:
        self._load_payload = load_payload
        self._login_returns = login_returns
        self.login_calls: list[tuple[str, str]] = []
        self.load_calls: list[int] = []

    def login(self, username: str, password: str) -> str:
        self.login_calls.append((username, password))
        return self._login_returns

    def load_game_info(self, game_id: int) -> dict:
        self.load_calls.append(game_id)
        return copy.deepcopy(self._load_payload)


class TestRefreshGameInfo:
    @pytest.fixture
    def sample_info(self):
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            return json.load(f)

    def test_requires_password_when_no_stored_api_key(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        games, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(sample_info)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1"},
        )
        with pytest.raises(LoginCredentialsRequiredError, match="Login credentials are required"):
            games.update_game_info(628580, body, planets)
        assert planets.login_calls == []
        assert planets.load_calls == []

    def test_login_and_store_when_password_given(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        games, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(sample_info, login_returns="stored-key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        gi = games.update_game_info(628580, body, planets)
        assert planets.login_calls == [("player1", "secret")]
        assert planets.load_calls == [628580]
        assert backend.get("credentials/accounts/player1/api_key") == "stored-key"
        assert isinstance(gi, GameInfo)
        assert gi.game.id == 628580

    def test_skips_login_when_api_key_cached(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        backend.put("credentials/accounts/player1/api_key", "cached-key")
        games, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(sample_info)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1"},
        )
        games.update_game_info(628580, body, planets)
        assert planets.login_calls == []
        assert planets.load_calls == [628580]

    def test_wrong_game_id_from_host_raises(self, sample_info):
        bad = copy.deepcopy(sample_info)
        bad["game"]["id"] = 1
        backend = MemoryAssetBackend(initial={})
        games, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(bad)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "x"},
        )
        with pytest.raises(ValidationError, match="does not match"):
            games.update_game_info(628580, body, planets)

    def test_rejects_inconsistent_game_and_settings_turn(self, sample_info):
        bad = copy.deepcopy(sample_info)
        bad["settings"]["turn"] = 1
        backend = MemoryAssetBackend(initial={})
        games, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(bad)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "x"},
        )
        with pytest.raises(ValidationError, match="inconsistent"):
            games.update_game_info(628580, body, planets)
