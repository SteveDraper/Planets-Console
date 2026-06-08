"""Tests for finished-game loadall archive import and archive turn validation."""

import copy
import json
from unittest.mock import MagicMock

import pytest
from api.errors import LoginCredentialsRequiredError, NotFoundError, ValidationError
from api.services.game_service import GameService
from api.services.load_all_archive import ArchiveTurnFile
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import (
    LoadAllProgressUpdate,
    LoadAllTurnsResponse,
    load_all_stream_event_to_dict,
)
from conftest import (
    ASSETS_DIR,
    archive_turn_rst,
    final_load_all_result,
    load_services,
    mock_planets_load_game_info,
    zip_with,
)


def test_load_all_refreshes_stale_in_progress_info_for_finished_path() -> None:
    """Non-players may bulk-load finished games after live refresh reports status Finished."""
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        stale_payload = json.load(handle)
        fresh_payload = copy.deepcopy(stale_payload)
    stale_payload["game"]["status"] = 1
    stale_payload["game"]["statusname"] = "Running"
    stale_payload["game"]["turn"] = 1
    stale_payload["settings"]["turn"] = 1
    stale_payload["players"] = stale_payload["players"][:2]
    fresh_payload["game"]["id"] = 673864
    fresh_payload["game"]["turn"] = 1
    fresh_payload["settings"]["turn"] = 1
    fresh_payload["players"] = fresh_payload["players"][:2]
    stale_payload["game"]["id"] = 673864
    storage.put("games/673864/info", stale_payload)
    credentials.store_api_key("outsider", "api-key-1")

    zip_bytes = zip_with(
        {
            "player1-turn1.trn": archive_turn_rst(673864, 1),
            "player2-turn1.trn": archive_turn_rst(673864, 1),
        }
    )

    planets = MagicMock()
    mock_planets_load_game_info(planets, fresh_payload)
    planets.load_all.return_value = zip_bytes

    result = final_load_all_result(
        load_all,
        673864,
        RefreshGameInfoParams(username="outsider"),
        planets,
    )

    planets.load_game_info.assert_called_once_with(673864)
    assert result.is_game_finished is True
    assert storage.get("games/673864/1/turns/1") is not None
    assert storage.get("games/673864/2/turns/1") is not None


def test_load_finished_game_imports_spectator_when_archive_includes_player0() -> None:
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:1]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = zip_with(
        {
            "player0-turn1.trn": archive_turn_rst(628580, 1),
            "player1-turn1.trn": archive_turn_rst(628580, 1),
        }
    )

    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)

    def load_turn_side_effect(**kwargs):
        turn_number = kwargs.get("turn")
        if turn_number is None:
            turn_number = 2
        rst = json.loads(json.dumps(turn_rst))
        rst["settings"]["turn"] = turn_number
        rst["game"]["id"] = 628580
        rst["game"]["turn"] = turn_number
        return {"success": True, "rst": rst}

    planets = MagicMock()
    mock_planets_load_game_info(planets, info_payload)
    planets.load_all.return_value = zip_bytes
    planets.load_turn.side_effect = load_turn_side_effect

    result = final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )

    assert storage.get("games/628580/0/turns/1") is not None
    assert storage.get("games/628580/1/turns/1") is not None
    assert 0 in result.perspectives_touched
    assert 0 not in (result.final_turn_load_failures or [])
    assert storage.get("games/628580/0/turns/2") is not None


def test_load_finished_game_from_loadall_zip() -> None:
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 1
    info_payload["settings"]["turn"] = 1
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = zip_with(
        {
            "player1-turn1.trn": archive_turn_rst(628580, 1),
            "player2-turn1.trn": archive_turn_rst(628580, 1),
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
    mock_planets_load_game_info(planets, info_payload)
    planets.load_all.return_value = zip_bytes
    planets.load_turn.side_effect = load_turn_side_effect

    result = final_load_all_result(
        load_all,
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
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = zip_with(
        {
            "player1-turn1.trn": archive_turn_rst(628580, 1),
            "player2-turn1.trn": archive_turn_rst(628580, 1),
            "player1-turn2.trn": archive_turn_rst(628580, 2),
        }
    )

    planets = MagicMock()
    mock_planets_load_game_info(planets, info_payload)
    planets.load_all.return_value = zip_bytes
    planets.load_turn.return_value = {
        "success": True,
        "rst": archive_turn_rst(628580, 2),
    }

    items = list(
        load_all.iter_load_all_turns(
            628580,
            RefreshGameInfoParams(username="captain"),
            planets,
        )
    )
    progress = [item for item in items if isinstance(item, LoadAllProgressUpdate)]
    assert progress[0].phase == "download"
    import_events = [item for item in progress if item.phase == "import"]
    assert [item.perspective for item in import_events] == [1, 1, 2]
    assert isinstance(items[-1], LoadAllTurnsResponse)

    wire = [load_all_stream_event_to_dict(item) for item in items]
    assert wire[0]["type"] == "progress" and wire[0]["phase"] == "download"
    assert wire[-1]["type"] == "complete"


def test_load_all_turns_requires_login() -> None:
    _, _, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        from api.storage import get_storage

        get_storage().put("games/628580/info", json.load(handle))

    with pytest.raises(LoginCredentialsRequiredError):
        list(
            load_all.iter_load_all_turns(
                628580,
                RefreshGameInfoParams(username=""),
                MagicMock(),
            )
        )


def test_perspective_for_username_raises_when_not_in_game() -> None:
    storage, _, games, _, _ = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    info = games.get_game_info(628580)
    with pytest.raises(ValidationError):
        GameService.perspective_for_username(info, "not-a-player", 628580)


def test_store_archive_turn_if_missing_rejects_invalid_rst() -> None:
    storage, _, _, turns, _ = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))

    archive_turn = ArchiveTurnFile(
        player_slot=1,
        turn_number=1,
        rst={"settings": {"turn": 1}, "game": {"id": 628580, "turn": 1}},
    )

    with pytest.raises(ValidationError, match="Loadall archive turn rst"):
        turns.store_archive_turn_if_missing(628580, archive_turn)

    with pytest.raises(NotFoundError):
        storage.get("games/628580/1/turns/1")


def test_load_finished_game_from_loadall_rejects_invalid_archive_rst() -> None:
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 1
    info_payload["settings"]["turn"] = 1
    info_payload["players"] = info_payload["players"][:2]
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = zip_with(
        {
            "player1-turn1.trn": archive_turn_rst(628580, 1),
            "player2-turn1.trn": {"not": "a turn rst"},
        }
    )

    planets = MagicMock()
    mock_planets_load_game_info(planets, info_payload)
    planets.load_all.return_value = zip_bytes

    with pytest.raises(ValidationError, match="Loadall archive turn rst"):
        final_load_all_result(
            load_all,
            628580,
            RefreshGameInfoParams(username="captain"),
            planets,
        )

    assert storage.get("games/628580/1/turns/1") is not None
    with pytest.raises(NotFoundError):
        storage.get("games/628580/2/turns/1")


def test_store_archive_turn_rejects_settings_turn_mismatch(turn_rst) -> None:
    storage, _, _, turns, _ = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    rst = json.loads(json.dumps(turn_rst))
    rst["settings"]["turn"] = 99
    rst["game"]["id"] = 628580
    archive_turn = ArchiveTurnFile(player_slot=1, turn_number=1, rst=rst)

    with pytest.raises(ValidationError, match="settings.turn"):
        turns.store_archive_turn_if_missing(628580, archive_turn)


def test_store_archive_turn_rejects_wrong_game_id(turn_rst) -> None:
    storage, _, _, turns, _ = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    rst = json.loads(json.dumps(turn_rst))
    rst["settings"]["turn"] = 1
    rst["game"]["id"] = 999999
    archive_turn = ArchiveTurnFile(player_slot=1, turn_number=1, rst=rst)

    with pytest.raises(ValidationError, match="game.id"):
        turns.store_archive_turn_if_missing(628580, archive_turn)


def test_store_archive_turn_accepts_game_turn_mismatch(turn_rst) -> None:
    storage, _, _, turns, _ = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        storage.put("games/628580/info", json.load(handle))
    rst = json.loads(json.dumps(turn_rst))
    rst["settings"]["turn"] = 1
    rst["game"]["id"] = 628580
    rst["game"]["turn"] = 111
    archive_turn = ArchiveTurnFile(player_slot=1, turn_number=1, rst=rst)

    assert turns.store_archive_turn_if_missing(628580, archive_turn) is True
    stored = storage.get("games/628580/1/turns/1")
    assert stored["settings"]["turn"] == 1
    assert stored["game"]["turn"] == 111


def test_load_finished_game_skips_post_death_archive_turns() -> None:
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = 2
    info_payload["settings"]["turn"] = 2
    info_payload["players"] = info_payload["players"][:1]
    info_payload["players"][0]["status"] = 3
    info_payload["players"][0]["statusturn"] = 2
    info_payload["players"][0]["username"] = "dead"
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    zip_bytes = zip_with(
        {
            "player1-turn1.trn": archive_turn_rst(628580, 1),
            "player1-turn2.trn": archive_turn_rst(628580, 2),
            "player1-turn3.trn": archive_turn_rst(628580, 3),
        }
    )

    planets = MagicMock()
    mock_planets_load_game_info(planets, info_payload)
    planets.load_all.return_value = zip_bytes

    result = final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )

    assert result.is_game_finished is True
    assert storage.get("games/628580/1/turns/1") is not None
    assert storage.get("games/628580/1/turns/2") is not None
    with pytest.raises(NotFoundError):
        storage.get("games/628580/1/turns/3")
    planets.load_turn.assert_not_called()
