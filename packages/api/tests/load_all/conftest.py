"""Shared fixtures and helpers for load-all tests."""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.turn_load_service import TurnLoadService
from api.storage import clear_backend_cache, get_storage
from api.transport.game_info_update import RefreshGameInfoParams
from api.transport.load_all_turns import LoadAllTurnsResponse

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def turn_rst() -> dict:
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return json.load(handle)


def archive_turn_rst(game_id: int, turn_number: int) -> dict:
    """Build a loadall-archive-shaped rst that passes turn_info_from_json."""
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        rst = json.load(handle)
    rst = json.loads(json.dumps(rst))
    rst["settings"]["turn"] = turn_number
    rst["game"]["id"] = game_id
    rst["game"]["turn"] = turn_number
    return rst


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


def zip_with(entries: dict[str, dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, rst in entries.items():
            archive.writestr(name, json.dumps(rst))
    return buf.getvalue()


def load_services():
    storage = get_storage()
    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    turns = TurnLoadService(storage, credentials, games)
    load_all = LoadAllTurnsService(credentials, games, turns)
    return storage, credentials, games, turns, load_all


def put_minimal_turn(storage, game_id: int, perspective: int, turn_number: int) -> None:
    storage.put(
        f"games/{game_id}/{perspective}/turns/{turn_number}",
        {
            "settings": {"turn": turn_number},
            "game": {"id": game_id, "turn": turn_number},
        },
    )


def mock_planets_load_game_info(planets: MagicMock, info_payload: dict) -> None:
    """``iter_load_all_turns`` refreshes game info before choosing the bulk-load path."""
    planets.load_game_info.return_value = info_payload


def final_load_all_result(
    load_all: LoadAllTurnsService,
    game_id: int,
    params: RefreshGameInfoParams,
    planets: MagicMock,
) -> LoadAllTurnsResponse:
    result: LoadAllTurnsResponse | None = None
    for item in load_all.iter_load_all_turns(game_id, params, planets):
        if isinstance(item, LoadAllTurnsResponse):
            result = item
    assert result is not None
    return result
