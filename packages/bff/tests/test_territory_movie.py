"""BFF forwards the Territory movie body that Core packed."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.app import app as api_app
from api.compute.turn_cache import clear_process_turn_info_cache
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.serialization.game import game_info_from_json, game_info_to_json
from api.serialization.turn import turn_info_from_json, turn_info_to_json
from api.services.turn_load_service import TurnLoadService
from api.storage_factory import clear_backend_cache, get_storage
from bff.app import app
from bff.config import BffConfig
from bff.config import set_config as set_bff_config
from bff.core_client import clear_core_client_cache
from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=False)
ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "api" / "api" / "storage" / "assets"
_PERSPECTIVE = 1


@pytest.fixture(autouse=True)
def _reset_storage():
    clear_backend_cache()
    clear_core_client_cache()
    clear_process_turn_info_cache()
    set_bff_config(BffConfig())
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    yield
    clear_core_client_cache()
    clear_process_turn_info_cache()
    clear_backend_cache()


def _store_turn(*, game_turn: int) -> int:
    raw_turn = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    turn = turn_info_from_json(raw_turn, settings_defaults=raw_turn["settings"])
    template = turn.planets[0]
    player = replace(turn.players[0], id=1, username="Ada", leagueteamid=0)
    turn = replace(
        turn,
        planets=[
            replace(template, id=1, x=1900, y=2000, ownerid=1),
            replace(template, id=2, x=2100, y=2000, ownerid=0),
        ],
        players=[player],
        player=player,
        settings=replace(turn.settings, turn=1),
    )
    info = game_info_from_json(
        json.loads((ASSETS_DIR / "game_info_sample.json").read_text(encoding="utf-8"))
    )
    game_id = info.game.id
    info = replace(info, game=replace(info.game, turn=game_turn), players=[player])
    storage = get_storage()
    storage.put(f"games/{game_id}/info", game_info_to_json(info))
    storage.put(
        TurnLoadService.turn_store_key(game_id, _PERSPECTIVE, 1),
        turn_info_to_json(turn),
    )
    return game_id


def test_bff_territory_movie_returns_core_body() -> None:
    game_id = _store_turn(game_turn=1)
    core = TestClient(api_app, raise_server_exceptions=False)
    path = f"/games/{game_id}/{_PERSPECTIVE}/territory-movie"
    bff_response = client.get(path)
    core_response = core.get(f"/v1{path}")
    assert bff_response.status_code == 200
    assert core_response.status_code == 200
    assert bff_response.json() == core_response.json()
    body = bff_response.json()
    assert body["turn"] == 1
    assert body["players"] == [{"id": 1, "name": "Ada"}]
    assert body["teams"] == []


def test_bff_missing_turn_matches_core() -> None:
    game_id = _store_turn(game_turn=2)
    core = TestClient(api_app, raise_server_exceptions=False)
    path = f"/games/{game_id}/{_PERSPECTIVE}/territory-movie"
    bff_response = client.get(path)
    core_response = core.get(f"/v1{path}")
    assert bff_response.status_code == 404
    assert bff_response.json() == core_response.json()
    assert "turn 2" in bff_response.json()["detail"]
