"""Tests for finished-game final-turn loading after loadall archive import."""

import json
from unittest.mock import MagicMock

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.errors import UpstreamPlanetsError, ValidationError
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_final_turns import (
    FinalTurnLoadResult,
    iter_final_turn_load_progress,
)
from api.services.turn_load_service import TurnLoadService
from api.storage import clear_backend_cache, get_storage
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import LoadAllProgressUpdate

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


def _load_turns() -> tuple[TurnLoadService, CredentialService]:
    storage = get_storage()
    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    return TurnLoadService(storage, credentials, games), credentials


def _put_minimal_turn(game_id: int, perspective: int, turn_number: int) -> None:
    get_storage().put(
        f"games/{game_id}/{perspective}/turns/{turn_number}",
        {
            "settings": {"turn": turn_number},
            "game": {"id": game_id, "turn": turn_number},
        },
    )


def _setup_finished_game(*, player_count: int = 2, latest_turn: int = 2) -> None:
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["turn"] = latest_turn
    info_payload["settings"]["turn"] = latest_turn
    info_payload["players"] = info_payload["players"][:player_count]
    get_storage().put("games/628580/info", info_payload)


def _turn_rst(turn_number: int) -> dict:
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        rst = json.load(handle)
    rst = json.loads(json.dumps(rst))
    rst["settings"]["turn"] = turn_number
    rst["game"]["id"] = 628580
    rst["game"]["turn"] = turn_number
    return rst


def test_iter_final_turn_load_progress_skips_already_stored() -> None:
    turns, credentials = _load_turns()
    _setup_finished_game()
    credentials.store_api_key("captain", "api-key-1")
    _put_minimal_turn(628580, 1, 2)
    _put_minimal_turn(628580, 2, 2)

    result = FinalTurnLoadResult()
    progress = list(
        iter_final_turn_load_progress(
            turns,
            628580,
            2,
            RefreshGameInfoParams(username="captain"),
            MagicMock(),
            2,
            result,
        )
    )

    assert len(progress) == 2
    assert all(item.phase == "final_turn" for item in progress)
    assert progress[0].message == "Final turn already stored (perspective 1)"
    assert progress[1].message == "Final turn already stored (perspective 2)"
    assert result.turns_skipped == 2
    assert result.turns_written == 0
    assert result.failures == []


def test_iter_final_turn_load_progress_loads_missing_final_turns() -> None:
    turns, credentials = _load_turns()
    _setup_finished_game()
    credentials.store_api_key("captain", "api-key-1")

    planets = MagicMock()
    planets.load_turn.return_value = {"success": True, "rst": _turn_rst(2)}

    result = FinalTurnLoadResult()
    progress = list(
        iter_final_turn_load_progress(
            turns,
            628580,
            2,
            RefreshGameInfoParams(username="captain"),
            planets,
            2,
            result,
        )
    )

    assert len(progress) == 2
    assert progress[0].message == "Loading final turn for perspective 1"
    assert progress[1].message == "Loading final turn for perspective 2"
    assert result.turns_written == 2
    assert result.perspectives_touched == {1, 2}
    assert result.failures == []
    assert get_storage().get("games/628580/1/turns/2") is not None
    assert get_storage().get("games/628580/2/turns/2") is not None


def test_iter_final_turn_load_progress_records_failures() -> None:
    turns, credentials = _load_turns()
    _setup_finished_game()
    credentials.store_api_key("captain", "api-key-1")

    planets = MagicMock()
    planets.load_turn.side_effect = UpstreamPlanetsError("upstream unavailable")

    result = FinalTurnLoadResult()
    progress = list(
        iter_final_turn_load_progress(
            turns,
            628580,
            2,
            RefreshGameInfoParams(username="captain"),
            planets,
            2,
            result,
        )
    )

    assert len(progress) == 2
    assert result.turns_written == 0
    assert result.failures == [1, 2]


def test_iter_final_turn_load_progress_no_op_when_latest_turn_zero() -> None:
    turns, credentials = _load_turns()
    _setup_finished_game(latest_turn=0)
    credentials.store_api_key("captain", "api-key-1")

    result = FinalTurnLoadResult()
    progress = list(
        iter_final_turn_load_progress(
            turns,
            628580,
            0,
            RefreshGameInfoParams(username="captain"),
            MagicMock(),
            2,
            result,
        )
    )

    assert progress == []
    assert result.turns_written == 0
    assert result.turns_skipped == 0
    assert result.failures == []


def test_iter_final_turn_load_progress_records_partial_failures() -> None:
    turns, credentials = _load_turns()
    _setup_finished_game(player_count=3)
    credentials.store_api_key("captain", "api-key-1")
    _put_minimal_turn(628580, 1, 2)

    planets = MagicMock()

    def load_turn_side_effect(**kwargs):
        player_id = kwargs.get("player_id")
        if player_id == 2:
            raise ValidationError("bad turn")
        return {"success": True, "rst": _turn_rst(2)}

    planets.load_turn.side_effect = load_turn_side_effect

    result = FinalTurnLoadResult()
    list(
        iter_final_turn_load_progress(
            turns,
            628580,
            2,
            RefreshGameInfoParams(username="captain"),
            planets,
            3,
            result,
        )
    )

    assert result.failures == [2]
    assert get_storage().get("games/628580/3/turns/2") is not None


def test_final_turn_progress_uses_one_based_perspective_index() -> None:
    turns, credentials = _load_turns()
    _setup_finished_game(player_count=3, latest_turn=1)
    credentials.store_api_key("captain", "api-key-1")
    for perspective in range(1, 4):
        _put_minimal_turn(628580, perspective, 1)

    result = FinalTurnLoadResult()
    progress = list(
        iter_final_turn_load_progress(
            turns,
            628580,
            1,
            RefreshGameInfoParams(username="captain"),
            MagicMock(),
            3,
            result,
        )
    )

    assert [item.perspective for item in progress] == [1, 2, 3]
    assert all(item.perspective_total == 3 for item in progress)
    assert all(item.turn == 1 and item.turn_total == 1 for item in progress)
    assert all(isinstance(item, LoadAllProgressUpdate) for item in progress)
