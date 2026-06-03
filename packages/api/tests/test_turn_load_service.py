"""Tests for TurnLoadService."""

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from api.errors import (
    LoginCredentialsRequiredError,
    NotFoundError,
    UpstreamPlanetsError,
    ValidationError,
)
from api.models.game import TurnInfo
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_archive import ArchiveTurnFile
from api.services.stack import build_service_stack
from api.services.turn_load_service import TurnLoadService
from api.storage.memory_asset import MemoryAssetBackend
from api.transport.game_info_update import RefreshGameInfoParams

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def turn_rst():
    with open(ASSETS_DIR / "turn_sample.json") as f:
        return json.load(f)


@pytest.fixture
def seeded_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    return backend


@pytest.fixture
def turn_load_service(seeded_backend):
    _, turns, _, _, _ = build_service_stack(seeded_backend)
    return turns


class TestListStoredTurnPerspectives:
    def test_returns_perspectives_with_turn_in_storage(self, turn_load_service):
        assert turn_load_service.list_stored_turn_perspectives(628580, 111) == [1]

    def test_empty_when_turn_missing(self, turn_load_service):
        assert turn_load_service.list_stored_turn_perspectives(628580, 999) == []

    def test_empty_when_game_missing(self, turn_load_service):
        assert turn_load_service.list_stored_turn_perspectives(999999, 111) == []

    def test_lists_turn_prefix_without_getting_turn_documents(self):
        storage = MagicMock()
        storage.list.side_effect = [
            ["1", "2"],
            ["111"],
            ["111", "110"],
        ]
        credentials = CredentialService(storage)
        games = GameService(storage, credentials)
        turns = TurnLoadService(storage, credentials, games)

        assert turns.list_stored_turn_perspectives(628580, 111) == [1, 2]

        storage.get.assert_not_called()
        storage.list.assert_any_call("games/628580")
        storage.list.assert_any_call("games/628580/1/turns")
        storage.list.assert_any_call("games/628580/2/turns")

    def test_includes_pseudo_perspective_zero(self):
        storage = MagicMock()
        storage.list.side_effect = [
            ["0", "1"],
            ["111"],
            ["111"],
        ]
        credentials = CredentialService(storage)
        games = GameService(storage, credentials)
        turns = TurnLoadService(storage, credentials, games)

        assert turns.list_stored_turn_perspectives(628580, 111) == [0, 1]


class TestGetTurnInfo:
    def test_returns_turn_info(self, turn_load_service):
        ti = turn_load_service.get_turn_info(628580, 1, 111)
        assert isinstance(ti, TurnInfo)
        assert ti.settings.turn == 111

    def test_backfills_historical_settings_from_stored_game_info(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        historical = copy.deepcopy(turn_rst)
        del historical["settings"]["allplanetsvisible"]
        del historical["settings"]["spectatormode"]
        backend.put("games/628580/1/turns/50", historical)
        _, turns, _, _, _ = build_service_stack(backend)
        ti = turns.get_turn_info(628580, 1, 50)
        assert ti.settings.allplanetsvisible is False
        assert ti.settings.spectatormode is False

    def test_planets_populated(self, turn_load_service):
        ti = turn_load_service.get_turn_info(628580, 1, 111)
        assert len(ti.planets) > 0

    def test_ships_populated(self, turn_load_service):
        ti = turn_load_service.get_turn_info(628580, 1, 111)
        assert len(ti.ships) > 0

    def test_skips_game_info_fetch_when_turn_settings_complete(self, turn_rst):
        storage = MagicMock()
        storage.get.return_value = turn_rst
        credentials = CredentialService(storage)
        games = GameService(storage, credentials)
        turns = TurnLoadService(storage, credentials, games)

        turns.get_turn_info(628580, 1, 111)

        storage.get.assert_called_once_with("games/628580/1/turns/111")

    def test_settings_defaults_fetched_once_for_multiple_historical_turns(self, turn_rst):
        storage = MagicMock()
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            game_info = json.load(f)
        historical_a = copy.deepcopy(turn_rst)
        historical_b = copy.deepcopy(turn_rst)
        del historical_a["settings"]["allplanetsvisible"]
        del historical_b["settings"]["spectatormode"]

        def get_side_effect(key: str):
            if key == "games/628580/info":
                return game_info
            if key == "games/628580/1/turns/50":
                return historical_a
            if key == "games/628580/1/turns/51":
                return historical_b
            raise NotFoundError(key)

        storage.get.side_effect = get_side_effect
        credentials = CredentialService(storage)
        games = GameService(storage, credentials)
        turns = TurnLoadService(storage, credentials, games)

        turns.get_turn_info(628580, 1, 50)
        turns.get_turn_info(628580, 1, 51)

        info_fetches = [
            get_call
            for get_call in storage.get.call_args_list
            if get_call.args[0] == "games/628580/info"
        ]
        assert len(info_fetches) == 1

    def test_not_found_game(self, turn_load_service):
        with pytest.raises(NotFoundError):
            turn_load_service.get_turn_info(999999, 1, 111)

    def test_not_found_turn(self, turn_load_service):
        with pytest.raises(NotFoundError):
            turn_load_service.get_turn_info(628580, 1, 999)


class TestGetPlanetFromTurn:
    def test_returns_planet_by_id(self, turn_load_service):
        p = turn_load_service.get_planet_from_turn(628580, 1, 111, 1)
        assert p.id == 1
        assert p.name == "Lorthidonia"

    def test_unknown_planet_id_raises(self, turn_load_service):
        with pytest.raises(NotFoundError, match="No planet id"):
            turn_load_service.get_planet_from_turn(628580, 1, 111, 999999999)


class TestTurnStoreKeyAndIsTurnStored:
    def test_turn_store_key_format(self) -> None:
        assert TurnLoadService.turn_store_key(628580, 1, 111) == "games/628580/1/turns/111"

    def test_is_turn_stored_false_when_missing(self, turn_load_service) -> None:
        assert turn_load_service.is_turn_stored(628580, 1, 999) is False

    def test_is_turn_stored_true_when_present(self, turn_load_service) -> None:
        assert turn_load_service.is_turn_stored(628580, 1, 111) is True


class TestStoreArchiveTurnIfMissing:
    def test_writes_turn_when_missing(self, turn_rst) -> None:
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        archive_turn = ArchiveTurnFile(player_slot=1, turn_number=50, rst=copy.deepcopy(turn_rst))
        archive_turn.rst["settings"]["turn"] = 50
        archive_turn.rst["game"]["id"] = 628580

        assert turns.store_archive_turn_if_missing(628580, archive_turn) is True
        backend.get("games/628580/1/turns/50")

    def test_skips_when_already_stored(self, seeded_backend, turn_rst) -> None:
        _, turns, _, _, _ = build_service_stack(seeded_backend)
        archive_turn = ArchiveTurnFile(player_slot=1, turn_number=111, rst=turn_rst)
        assert turns.store_archive_turn_if_missing(628580, archive_turn) is False

    def test_rejects_settings_turn_mismatch(self, turn_rst) -> None:
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        rst = copy.deepcopy(turn_rst)
        rst["settings"]["turn"] = 42
        archive_turn = ArchiveTurnFile(player_slot=1, turn_number=50, rst=rst)

        with pytest.raises(ValidationError, match="settings.turn"):
            turns.store_archive_turn_if_missing(628580, archive_turn)
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/50")

    def test_rejects_game_id_mismatch(self, turn_rst) -> None:
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        rst = copy.deepcopy(turn_rst)
        rst["settings"]["turn"] = 50
        rst["game"]["id"] = 999999
        archive_turn = ArchiveTurnFile(player_slot=1, turn_number=50, rst=rst)

        with pytest.raises(ValidationError, match="game.id"):
            turns.store_archive_turn_if_missing(628580, archive_turn)
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/50")

    def test_accepts_game_turn_different_from_archive_turn(self, turn_rst) -> None:
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        rst = copy.deepcopy(turn_rst)
        rst["settings"]["turn"] = 50
        rst["game"]["id"] = 628580
        rst["game"]["turn"] = 111
        archive_turn = ArchiveTurnFile(player_slot=1, turn_number=50, rst=rst)

        assert turns.store_archive_turn_if_missing(628580, archive_turn) is True
        stored = backend.get("games/628580/1/turns/50")
        assert stored["game"]["turn"] == 111
        assert stored["settings"]["turn"] == 50


class TestMalformedTurnStoreData:
    def test_turn_info_non_dict_raises_validation(self):
        backend = MemoryAssetBackend(initial={})
        backend.put("games/1/1/turns/1", "just a string")
        _, turns, _, _, _ = build_service_stack(backend)
        with pytest.raises(ValidationError, match="Expected JSON object"):
            turns.get_turn_info(1, 1, 1)

    def test_turn_info_shape_error_includes_field_detail(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        historical = copy.deepcopy(turn_rst)
        del historical["settings"]["allplanetsvisible"]
        backend.put("games/1/1/turns/1", historical)
        _, turns, _, _, _ = build_service_stack(backend)
        with pytest.raises(ValidationError, match="settings\\.allplanetsvisible"):
            turns.get_turn_info(1, 1, 1)


class FakePlanetsNu:
    def __init__(self, load_payload: dict, *, login_returns: str = "fake-api-key") -> None:
        self._load_payload = load_payload
        self._login_returns = login_returns
        self.login_calls: list[tuple[str, str]] = []
        self.load_calls: list[int] = []
        self.load_turn_calls: list[tuple[int, int | None, int]] = []

    def login(self, username: str, password: str) -> str:
        self.login_calls.append((username, password))
        return self._login_returns

    def load_game_info(self, game_id: int) -> dict:
        self.load_calls.append(game_id)
        return copy.deepcopy(self._load_payload)

    def load_turn(
        self, *, game_id: int, turn: int | None, player_id: int, api_key: str | None = None
    ):
        self.load_turn_calls.append((game_id, turn, player_id))
        raise AssertionError("load_turn must be overridden when used")


class FakePlanetsNuWithTurn(FakePlanetsNu):
    def __init__(self, load_payload: dict, rst_payload: dict, **kwargs) -> None:
        super().__init__(load_payload, **kwargs)
        self._rst = rst_payload

    def load_turn(
        self, *, game_id: int, turn: int | None, player_id: int, api_key: str | None = None
    ):
        self.load_turn_calls.append((game_id, turn, player_id))
        return {"success": True, "rst": copy.deepcopy(self._rst)}


class FakePlanetsNuWithTurnByUpstreamTurn(FakePlanetsNu):
    def __init__(
        self, load_payload: dict, rst_by_upstream_turn: dict[int | None, dict], **kwargs
    ) -> None:
        super().__init__(load_payload, **kwargs)
        self._rst_by_upstream_turn = rst_by_upstream_turn

    def load_turn(
        self, *, game_id: int, turn: int | None, player_id: int, api_key: str | None = None
    ):
        self.load_turn_calls.append((game_id, turn, player_id))
        if turn not in self._rst_by_upstream_turn:
            return {"success": False, "error": f"No stub for turn={turn!r}"}
        return {"success": True, "rst": copy.deepcopy(self._rst_by_upstream_turn[turn])}


class TestEnsureTurnLoaded:
    def test_returns_stored_turn_without_calling_planets(self, seeded_backend, turn_rst):
        _, turns, _, _, _ = build_service_stack(seeded_backend)
        planets = FakePlanetsNuWithTurn({}, turn_rst)
        params = RefreshGameInfoParams(username="player1", password="x")
        ti = turns.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert isinstance(ti, TurnInfo)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == []

    def test_allows_empty_username_when_turn_already_stored(self, seeded_backend, turn_rst):
        _, turns, _, _, _ = build_service_stack(seeded_backend)
        planets = FakePlanetsNuWithTurn({}, turn_rst)
        params = RefreshGameInfoParams(username="")
        ti = turns.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == []

    def test_fetches_and_stores_when_missing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, turn_rst)
        backend.put("credentials/accounts/player1/api_key", "k")
        params = RefreshGameInfoParams(username="player1")
        ti = turns.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == [(628580, 111, 1)]
        backend.get("games/628580/1/turns/111")

    def test_fetches_with_pseudo_perspective_zero(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, turn_rst)
        backend.put("credentials/accounts/host/api_key", "k")
        params = RefreshGameInfoParams(username="host")
        ti = turns.ensure_turn_loaded(628580, 0, 111, params, planets)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == [(628580, None, 0)]
        backend.get("games/628580/0/turns/111")

    def test_fetches_historical_spectator_turn_with_explicit_turn(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        historical = copy.deepcopy(turn_rst)
        historical["settings"]["turn"] = 110
        historical["game"]["turn"] = 110
        planets = FakePlanetsNuWithTurn(info, historical)
        backend.put("credentials/accounts/host/api_key", "k")
        params = RefreshGameInfoParams(username="host")
        ti = turns.ensure_turn_loaded(628580, 0, 110, params, planets)
        assert ti.settings.turn == 110
        assert planets.load_turn_calls == [(628580, 110, 0)]
        backend.get("games/628580/0/turns/110")

    def test_rejects_wrong_turn_from_turnless_spectator_load_without_storing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        bad = copy.deepcopy(turn_rst)
        bad["settings"]["turn"] = 110
        bad["game"]["turn"] = 110
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurnByUpstreamTurn(info, {None: bad, 111: bad})
        backend.put("credentials/accounts/host/api_key", "k")
        params = RefreshGameInfoParams(username="host")
        _, turns, _, _, _ = build_service_stack(backend)
        with pytest.raises(UpstreamPlanetsError, match="settings.turn"):
            turns.ensure_turn_loaded(628580, 0, 111, params, planets)
        assert planets.load_turn_calls == [(628580, None, 0), (628580, 111, 0)]
        with pytest.raises(NotFoundError):
            backend.get("games/628580/0/turns/111")

    def test_retries_turnless_spectator_load_with_explicit_turn_when_game_info_stale(
        self, turn_rst
    ):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        newer = copy.deepcopy(turn_rst)
        newer["settings"]["turn"] = 112
        newer["game"]["turn"] = 112
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurnByUpstreamTurn(info, {None: newer, 111: turn_rst})
        backend.put("credentials/accounts/host/api_key", "k")
        params = RefreshGameInfoParams(username="host")
        _, turns, _, _, _ = build_service_stack(backend)
        ti = turns.ensure_turn_loaded(628580, 0, 111, params, planets)
        assert ti.settings.turn == 111
        assert planets.load_turn_calls == [(628580, None, 0), (628580, 111, 0)]
        backend.get("games/628580/0/turns/111")

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
        _, turns, _, _, _ = build_service_stack(backend)
        with pytest.raises(UpstreamPlanetsError, match="settings.turn"):
            turns.ensure_turn_loaded(628580, 1, 111, params, planets)
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
        _, turns, _, _, _ = build_service_stack(backend)
        with pytest.raises(UpstreamPlanetsError, match="game.id"):
            turns.ensure_turn_loaded(628580, 1, 111, params, planets)
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
        _, turns, _, _, _ = build_service_stack(backend)
        with pytest.raises(UpstreamPlanetsError, match="game.turn"):
            turns.ensure_turn_loaded(628580, 1, 111, params, planets)
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/111")

    def test_requires_password_when_no_key(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, turn_rst)
        params = RefreshGameInfoParams(username="player1")
        with pytest.raises(LoginCredentialsRequiredError):
            turns.ensure_turn_loaded(628580, 1, 42, params, planets)
        assert planets.load_turn_calls == []

    def test_rejects_empty_username_when_turn_missing(self, turn_rst):
        backend = MemoryAssetBackend(initial={})
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            backend.put("games/628580/info", json.load(f))
        _, turns, _, _, _ = build_service_stack(backend)
        with open(ASSETS_DIR / "game_info_sample.json") as f:
            info = json.load(f)
        planets = FakePlanetsNuWithTurn(info, turn_rst)
        params = RefreshGameInfoParams(username="")
        with pytest.raises(LoginCredentialsRequiredError, match="not already in storage"):
            turns.ensure_turn_loaded(628580, 1, 111, params, planets)
        assert planets.load_turn_calls == []
        with pytest.raises(NotFoundError):
            backend.get("games/628580/1/turns/111")
