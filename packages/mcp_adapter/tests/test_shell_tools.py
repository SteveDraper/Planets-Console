"""In-process remaining MCP shell tools: wrap mapping and eligibility refuse."""

from __future__ import annotations

from unittest.mock import MagicMock

from api.models.game import GameInfo
from api.planets_nu import PlanetsNuClient
from api.serialization.game import game_info_to_json
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from mcp import Client
from mcp_adapter.server import (
    ENSURE_TURN_TOOL,
    GET_GAME_INFO_TOOL,
    LIST_STORED_PERSPECTIVES_TOOL,
    REFRESH_GAME_INFO_TOOL,
)

from tests.mcp_test_support import build_test_mcp, resolve_as, run_coro

_GAME_ID = 628580
_TURN = 111


def _call(mcp, name: str, arguments: dict):
    async def body():
        async with Client(mcp) as client:
            return await client.call_tool(name, arguments)

    return run_coro(body())


def test_get_game_info_wraps_stored_game_info(sample_game_info: GameInfo):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = sample_game_info
    mcp = build_test_mcp(game_service=games)

    result = _call(mcp, GET_GAME_INFO_TOOL, {"game_id": _GAME_ID})

    assert result.is_error is False
    assert result.structured_content == game_info_to_json(sample_game_info)
    games.get_game_info.assert_called_once_with(_GAME_ID)


def test_refresh_game_info_uses_login_and_stored_key(sample_game_info: GameInfo):
    games = MagicMock(spec=GameService)
    games.refresh_game_info.return_value = sample_game_info
    planets = MagicMock(spec=PlanetsNuClient)
    mcp = build_test_mcp(
        game_service=games,
        resolve_login=resolve_as("alice"),
        planets_client_factory=lambda: planets,
    )

    result = _call(mcp, REFRESH_GAME_INFO_TOOL, {"game_id": _GAME_ID})

    assert result.is_error is False
    assert result.structured_content == game_info_to_json(sample_game_info)
    games.refresh_game_info.assert_called_once()
    game_id, params, client = games.refresh_game_info.call_args[0]
    assert game_id == _GAME_ID
    assert params.username == "alice"
    assert params.password is None
    assert client is planets


def test_ensure_turn_already_stored_does_not_return_turn_info(
    running_game_info: GameInfo,
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = True
    planets_factory = MagicMock(return_value=MagicMock(spec=PlanetsNuClient))
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
        planets_client_factory=planets_factory,
    )

    result = _call(
        mcp,
        ENSURE_TURN_TOOL,
        {"game_id": _GAME_ID, "turn": _TURN, "perspective": 2},
    )

    assert result.is_error is False
    assert result.structured_content == {"status": "already_stored"}
    assert set(result.structured_content) == {"status"}
    turns.ensure_turn_loaded.assert_not_called()
    planets_factory.assert_not_called()


def test_ensure_turn_loaded_discards_turn_info_blob(running_game_info: GameInfo):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = False
    blob = MagicMock()
    blob.planets = [{"id": 1}]
    blob.ships = [{"id": 99}]
    turns.ensure_turn_loaded.return_value = blob
    planets = MagicMock(spec=PlanetsNuClient)
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
        planets_client_factory=lambda: planets,
    )

    result = _call(
        mcp,
        ENSURE_TURN_TOOL,
        {"game_id": _GAME_ID, "turn": _TURN, "perspective": 2},
    )

    assert result.is_error is False
    assert result.structured_content == {"status": "loaded"}
    assert "planets" not in result.structured_content
    assert "ships" not in result.structured_content
    game_id, perspective, turn_number, params, client = turns.ensure_turn_loaded.call_args[0]
    assert (game_id, perspective, turn_number) == (_GAME_ID, 2, _TURN)
    assert params.username == "arlowat"
    assert params.password is None
    assert client is planets


def test_ensure_turn_refuses_ineligible_perspective(running_game_info: GameInfo):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = True
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
    )

    result = _call(
        mcp,
        ENSURE_TURN_TOOL,
        {"game_id": _GAME_ID, "turn": _TURN, "perspective": 1},
    )

    assert result.is_error is True
    text = result.content[0].text
    assert "Perspective 1 is not allowed" in text
    assert "arlowat" in text
    turns.is_turn_stored.assert_not_called()
    turns.ensure_turn_loaded.assert_not_called()


def test_list_stored_perspectives_filters_to_eligible_slots(
    running_game_info: GameInfo,
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.list_stored_turn_perspectives.return_value = [0, 1, 2]
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
    )

    result = _call(
        mcp,
        LIST_STORED_PERSPECTIVES_TOOL,
        {"game_id": _GAME_ID, "turn": _TURN},
    )

    assert result.is_error is False
    assert result.structured_content == {"perspectives": [2]}
    turns.list_stored_turn_perspectives.assert_called_once_with(_GAME_ID, _TURN)


def test_list_stored_perspectives_finished_game_keeps_player_slots(
    sample_game_info: GameInfo,
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = sample_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.list_stored_turn_perspectives.return_value = [0, 1, 2]
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("nobody"),
    )

    result = _call(
        mcp,
        LIST_STORED_PERSPECTIVES_TOOL,
        {"game_id": _GAME_ID, "turn": _TURN},
    )

    assert result.is_error is False
    assert result.structured_content == {"perspectives": [1, 2]}
