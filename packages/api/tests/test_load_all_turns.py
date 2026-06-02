"""Tests for bulk turn loading."""

import io
import json
import zipfile
from unittest.mock import MagicMock

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.errors import LoginCredentialsRequiredError, ValidationError
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.storage import clear_backend_cache, get_storage
from api.transport.game_info_update import RefreshGameInfoParams

ASSETS_DIR = (
    __import__("pathlib").Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
)


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


def _zip_with(entries: dict[str, dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, rst in entries.items():
            archive.writestr(name, json.dumps(rst))
    return buf.getvalue()


def _load_services():
    storage = get_storage()
    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    turns = TurnLoadService(storage, credentials, games)
    return storage, credentials, games, turns


def test_load_all_turns_status_complete_when_all_turns_present() -> None:
    storage, _, games, turns = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    latest = info_payload["game"]["turn"]
    for perspective in range(1, len(info_payload["players"]) + 1):
        for turn_number in range(1, latest + 1):
            storage.put(
                f"games/628580/{perspective}/turns/{turn_number}",
                {"settings": {"turn": turn_number}, "game": {"id": 628580, "turn": turn_number}},
            )

    status = turns.load_all_turns_status_for_user(628580, "anyone")
    assert status.complete is True
    assert status.is_game_finished is True
    assert status.latest_turn == latest


def test_load_all_turns_status_incomplete_when_turn_missing() -> None:
    storage, _, _, turns = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    storage.put("games/628580/info", info_payload)
    storage.put(
        "games/628580/1/turns/1",
        {"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
    )

    status = turns.load_all_turns_status_for_user(628580, "player")
    assert status.complete is False


def test_load_finished_game_from_loadall_zip() -> None:
    storage, credentials, _, turns = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 1
    info_payload["settings"]["turn"] = 1
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = _zip_with(
        {
            "player1-turn1.trn": {"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
            "player2-turn1.trn": {"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
        }
    )

    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)

    def load_turn_side_effect(**kwargs):
        turn_number = kwargs.get("turn")
        rst = json.loads(json.dumps(turn_rst))
        rst["settings"]["turn"] = turn_number
        rst["game"]["id"] = 628580
        rst["game"]["turn"] = turn_number
        return {"success": True, "rst": rst}

    planets = MagicMock()
    planets.load_all.return_value = zip_bytes
    planets.load_turn.side_effect = load_turn_side_effect

    result = turns.load_all_turns(
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )
    assert result.is_game_finished is True
    assert result.turns_written >= 2
    assert storage.get("games/628580/1/turns/1") is not None
    assert storage.get("games/628580/2/turns/1") is not None
    planets.load_all.assert_called_once_with(628580)


def test_iter_load_all_turns_emits_perspective_first_progress() -> None:
    storage, credentials, _, turns = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = _zip_with(
        {
            "player1-turn1.trn": {"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
            "player2-turn1.trn": {"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
            "player1-turn2.trn": {"settings": {"turn": 2}, "game": {"id": 628580, "turn": 2}},
        }
    )

    planets = MagicMock()
    planets.load_all.return_value = zip_bytes
    planets.load_turn.return_value = {
        "success": True,
        "rst": {"settings": {"turn": 2}, "game": {"id": 628580, "turn": 2}},
    }

    events = list(
        turns.iter_load_all_turns(
            628580,
            RefreshGameInfoParams(username="captain"),
            planets,
        )
    )
    progress = [event for event in events if event["type"] == "progress"]
    assert progress[0]["phase"] == "download"
    import_events = [event for event in progress if event["phase"] == "import"]
    assert [event["perspective"] for event in import_events] == [1, 1, 2]
    assert events[-1]["type"] == "complete"


def test_load_all_turns_requires_login() -> None:
    _, _, _, turns = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        get_storage().put("games/628580/info", json.load(handle))

    with pytest.raises(LoginCredentialsRequiredError):
        turns.load_all_turns(
            628580,
            RefreshGameInfoParams(username=""),
            MagicMock(),
        )


def test_perspective_for_username_raises_when_not_in_game() -> None:
    storage, _, games, _ = _load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    info = games.get_game_info(628580)
    with pytest.raises(ValidationError):
        GameService.perspective_for_username(info, "not-a-player", 628580)
