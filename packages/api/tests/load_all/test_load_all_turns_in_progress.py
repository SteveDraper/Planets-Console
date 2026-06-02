"""Tests for in-progress game bulk load via loadturn."""

import json
from unittest.mock import MagicMock

import pytest
from api.errors import NotFoundError
from api.transport.game_info_update import RefreshGameInfoParams
from conftest import ASSETS_DIR, archive_turn_rst, final_load_all_result, load_services


def test_load_in_progress_game_stops_at_elimination_turn() -> None:
    storage, credentials, _, _, load_all = load_services()
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        info_payload = json.load(handle)
    info_payload["game"]["status"] = 1
    info_payload["game"]["turn"] = 5
    info_payload["settings"]["turn"] = 5
    info_payload["players"] = info_payload["players"][:1]
    info_payload["players"][0]["status"] = 3
    info_payload["players"][0]["statusturn"] = 2
    info_payload["players"][0]["username"] = "captain"
    storage.put("games/628580/info", info_payload)
    credentials.store_api_key("captain", "api-key-1")

    planets = MagicMock()

    def load_turn_side_effect(**kwargs):
        turn_number = kwargs.get("turn")
        return {"success": True, "rst": archive_turn_rst(628580, turn_number)}

    planets.load_turn.side_effect = load_turn_side_effect

    result = final_load_all_result(
        load_all,
        628580,
        RefreshGameInfoParams(username="captain"),
        planets,
    )

    assert result.is_game_finished is False
    assert planets.load_turn.call_count == 2
    assert storage.get("games/628580/1/turns/1") is not None
    assert storage.get("games/628580/1/turns/2") is not None
    with pytest.raises(NotFoundError):
        storage.get("games/628580/1/turns/3")
