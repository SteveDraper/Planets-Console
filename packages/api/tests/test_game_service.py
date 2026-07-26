"""Tests for the GameService."""

import copy
import json
from pathlib import Path

import pytest
from api.errors import LoginCredentialsRequiredError, NotFoundError, ValidationError
from api.models.game import GameInfo
from api.models.game_info_operations import GameInfoUpdateOperation
from api.services.game_service import GameService, clear_sector_title_cache
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
    games, _, _, _, _, _ = build_service_stack(seeded_backend)
    return games


@pytest.fixture(autouse=True)
def _clear_sector_title_cache():
    clear_sector_title_cache()
    yield
    clear_sector_title_cache()


class TestListStoredGames:
    def test_returns_empty_when_games_path_missing(self):
        backend = MemoryAssetBackend(initial={})
        games, _, _, _, _, _ = build_service_stack(backend)
        assert games.list_stored_games() == {"games": []}

    def test_includes_sector_name_from_stored_info(self, service):
        result = service.list_stored_games()
        hit = next(g for g in result["games"] if g["id"] == "628580")
        assert hit.get("sectorName") == "Serada 9 Sector"

    def test_remember_sector_title_avoids_re_read_on_second_list(self):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            payload = json.load(f)
        backend.put("games/111/info", payload)
        backend.put("games/222/info", payload)
        games, _, _, _, _, _ = build_service_stack(backend)

        info_reads: list[str] = []
        original_get = backend.get

        def counting_get(path: str) -> object:
            if path.startswith("games/") and path.endswith("/info"):
                info_reads.append(path)
            return original_get(path)

        backend.get = counting_get  # type: ignore[method-assign]
        games.list_stored_games()
        games.list_stored_games()
        assert info_reads == ["games/111/info", "games/222/info"]

    def test_refresh_updates_sector_title_cache(self, game_info_sample_data):
        backend = MemoryAssetBackend(initial={})
        games, _, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(game_info_sample_data, login_returns="key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        games.update_game_info(628580, body, planets)
        result = games.list_stored_games()
        hit = next(g for g in result["games"] if g["id"] == "628580")
        assert hit.get("sectorName") == "Serada 9 Sector"


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

    def test_perspective_for_player_id(self, service):
        gi = service.get_game_info(628580)
        player_id = gi.players[0].id
        assert GameService.perspective_for_player_id(gi, player_id, 628580) == 1

    def test_perspective_for_player_id_unknown_raises(self, service):
        gi = service.get_game_info(628580)
        with pytest.raises(ValidationError, match="not in game"):
            GameService.perspective_for_player_id(gi, 999999, 628580)

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
        games, _, _, _, _, _ = build_service_stack(backend)
        with pytest.raises(ValidationError, match="Expected JSON object"):
            games.get_game_info(1)

    def test_game_info_shape_error_includes_field_detail(self, game_info_sample_data):
        backend = MemoryAssetBackend(initial={})
        bad = copy.deepcopy(game_info_sample_data)
        del bad["settings"]["id"]
        backend.put("games/628580/info", bad)
        games, _, _, _, _, _ = build_service_stack(backend)
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
        games, _, _, _, _, _ = build_service_stack(backend)
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
        games, _, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(sample_info, login_returns="stored-key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        gi = games.update_game_info(628580, body, planets)
        assert planets.login_calls == [("player1", "secret")]
        assert planets.load_calls == [628580]
        stored = backend.get("credentials/accounts/player1/api_key")
        from api.credentials.obfuscation import is_obfuscated_envelope
        from api.services.credential_service import CredentialService

        assert is_obfuscated_envelope(stored)
        assert CredentialService(backend).get_stored_api_key("player1") == "stored-key"
        assert isinstance(gi, GameInfo)
        assert gi.game.id == 628580

    def test_skips_login_when_api_key_cached(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        backend.put("credentials/accounts/player1/api_key", "cached-key")
        games, _, _, _, _, _ = build_service_stack(backend)
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
        games, _, _, _, _, _ = build_service_stack(backend)
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
        games, _, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(bad)
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "x"},
        )
        with pytest.raises(ValidationError, match="inconsistent"):
            games.update_game_info(628580, body, planets)

    def test_notifies_on_game_info_refreshed_with_previous_and_updated(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        backend.put("games/628580/info", copy.deepcopy(sample_info))
        notifications: list[tuple[int, GameInfo | None, GameInfo]] = []

        games = GameService(
            backend,
            on_game_info_refreshed=lambda game_id, previous, updated: notifications.append(
                (game_id, previous, updated)
            ),
        )
        planets = FakePlanetsNu(sample_info, login_returns="key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        result = games.update_game_info(628580, body, planets)
        assert len(notifications) == 1
        game_id, previous, updated = notifications[0]
        assert game_id == 628580
        assert previous is not None
        assert previous.game.id == 628580
        assert updated is result

    def test_notifies_on_first_refresh_with_previous_none(self, sample_info):
        backend = MemoryAssetBackend(initial={})
        notifications: list[tuple[int, GameInfo | None, GameInfo]] = []
        games = GameService(
            backend,
            on_game_info_refreshed=lambda game_id, previous, updated: notifications.append(
                (game_id, previous, updated)
            ),
        )
        planets = FakePlanetsNu(sample_info, login_returns="key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        games.update_game_info(628580, body, planets)
        assert len(notifications) == 1
        assert notifications[0][1] is None


class TestHomeworldSettingsInvalidationViaStack:
    """Stack owns homeworld fingerprint checks; GameService stays feature-agnostic."""

    @pytest.fixture
    def sample_info(self):
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            return json.load(f)

    def _seed_inferred_homeworld_state(self, backend: MemoryAssetBackend) -> None:
        from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
        from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
        from api.analytics.homeworld_locator.types import (
            HomeworldCandidateRecord,
            HomeworldLocatorGameState,
        )

        persistence = HomeworldLocatorPersistenceService(backend)
        persistence.put_game_state(
            628580,
            HomeworldLocatorGameState(
                candidates=(
                    HomeworldCandidateRecord(
                        planet_id=42,
                        perspective=1,
                        confidence_tier="definite",
                        attribution=ATTRIBUTION_INFERRED,
                    ),
                ),
                baseline_turn=1,
                baseline_degraded=False,
                settings_fingerprint=(1, 2, 3),
            ),
        )

    def test_homeworld_relevant_settings_change_invalidates_inferred_state(self, sample_info):
        from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService

        backend = MemoryAssetBackend(initial={})
        backend.put("games/628580/info", copy.deepcopy(sample_info))
        self._seed_inferred_homeworld_state(backend)

        refreshed = copy.deepcopy(sample_info)
        refreshed["settings"]["mapwidth"] = sample_info["settings"]["mapwidth"] + 50
        games, _, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(refreshed, login_returns="key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        games.update_game_info(628580, body, planets)

        persistence = HomeworldLocatorPersistenceService(backend)
        assert persistence.get_game_state(628580) is None

    def test_non_homeworld_settings_change_preserves_inferred_state(self, sample_info):
        from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService

        backend = MemoryAssetBackend(initial={})
        backend.put("games/628580/info", copy.deepcopy(sample_info))
        self._seed_inferred_homeworld_state(backend)

        refreshed = copy.deepcopy(sample_info)
        refreshed["settings"]["shiplimit"] = sample_info["settings"]["shiplimit"] + 1
        games, _, _, _, _, _ = build_service_stack(backend)
        planets = FakePlanetsNu(refreshed, login_returns="key")
        body = GameInfoUpdateRequest(
            operation=GameInfoUpdateOperation.REFRESH,
            params={"username": "player1", "password": "secret"},
        )
        games.update_game_info(628580, body, planets)

        persistence = HomeworldLocatorPersistenceService(backend)
        state = persistence.get_game_state(628580)
        assert state is not None
        assert state.candidates[0].planet_id == 42
