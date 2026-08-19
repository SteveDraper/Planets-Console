"""MCP TurnInfo fallback tools: whole-entity reads for a named id."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

from api.models.game import GameInfo, TurnInfo
from api.models.space import Wormhole
from api.models.starbase import Starbase
from api.serialization.codecs import dataclass_to_json
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from mcp_adapter.server import (
    GET_ION_STORM_TOOL,
    GET_MINEFIELD_TOOL,
    GET_PLANET_TOOL,
    GET_PLAYER_TOOL,
    GET_SHIP_TOOL,
    GET_WORMHOLE_TOOL,
)
from mcp_adapter.shell_context import NEEDS_ENSURE_RESULT
from mcp_adapter.turninfo_fallback import PLAYER_SECRET_FIELDS

from tests.mcp_test_support import build_test_mcp, call_tool, resolve_as

_GAME_ID = 628580
_TURN = 111
_PERSPECTIVE = 2
_SHELL = {"game_id": _GAME_ID, "turn": _TURN, "perspective": _PERSPECTIVE}

_SHIP_ID = 1
_PLANET_WITH_BASE_ID = 3
_PLANET_WITHOUT_BASE_ID = 1
_MINEFIELD_ID = 18
_ION_STORM_ID = 17
_PLAYER_ID = 1


def _stored_turn_mcp(running_game_info: GameInfo, turn: TurnInfo, *, login: str = "arlowat"):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = True
    turns.get_turn_info.return_value = turn
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as(login),
    )
    return mcp, games, turns


def _ship(turn: TurnInfo, ship_id: int):
    return next(ship for ship in turn.ships if ship.id == ship_id)


def _planet(turn: TurnInfo, planet_id: int):
    return next(planet for planet in turn.planets if planet.id == planet_id)


def _minefield(turn: TurnInfo, minefield_id: int):
    return next(field for field in turn.minefields if field.id == minefield_id)


def _ion_storm(turn: TurnInfo, ion_storm_id: int):
    return next(storm for storm in turn.ionstorms if storm.id == ion_storm_id)


def _player(turn: TurnInfo, player_id: int):
    return next(player for player in turn.players if player.id == player_id)


def _turn_with_starbase_id_mismatch(sample_turn: TurnInfo) -> tuple[TurnInfo, Starbase]:
    base = replace(
        sample_turn.starbases[0],
        id=_PLANET_WITHOUT_BASE_ID,
        planetid=_PLANET_WITH_BASE_ID,
    )
    return replace(sample_turn, starbases=[base]), base


def test_get_ship_returns_whole_stored_entity(running_game_info: GameInfo, sample_turn: TurnInfo):
    mcp, _, _ = _stored_turn_mcp(running_game_info, sample_turn)
    ship = _ship(sample_turn, _SHIP_ID)

    result = call_tool(mcp, GET_SHIP_TOOL, {**_SHELL, "ship_id": _SHIP_ID})

    assert result.is_error is False
    assert result.structured_content == dataclass_to_json(ship)


def test_get_planet_includes_starbase_keyed_by_planet_id(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    turn, base = _turn_with_starbase_id_mismatch(sample_turn)
    mcp, _, _ = _stored_turn_mcp(running_game_info, turn)
    planet = _planet(turn, _PLANET_WITH_BASE_ID)

    result = call_tool(mcp, GET_PLANET_TOOL, {**_SHELL, "planet_id": _PLANET_WITH_BASE_ID})

    assert result.is_error is False
    payload = result.structured_content
    expected = dataclass_to_json(planet)
    expected["starbase"] = dataclass_to_json(base)
    assert payload == expected
    assert payload["starbase"]["id"] == _PLANET_WITHOUT_BASE_ID
    assert payload["starbase"]["planetid"] == _PLANET_WITH_BASE_ID
    assert "buildingstarbase" in payload


def test_get_planet_does_not_match_starbase_by_rst_id(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    turn, _base = _turn_with_starbase_id_mismatch(sample_turn)
    mcp, _, _ = _stored_turn_mcp(running_game_info, turn)
    planet = _planet(turn, _PLANET_WITHOUT_BASE_ID)

    result = call_tool(mcp, GET_PLANET_TOOL, {**_SHELL, "planet_id": _PLANET_WITHOUT_BASE_ID})

    assert result.is_error is False
    expected = dataclass_to_json(planet)
    expected["starbase"] = None
    assert result.structured_content == expected


def test_get_planet_starbase_null_when_planet_has_no_base(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    mcp, _, _ = _stored_turn_mcp(running_game_info, sample_turn)

    result = call_tool(mcp, GET_PLANET_TOOL, {**_SHELL, "planet_id": _PLANET_WITHOUT_BASE_ID})

    assert result.is_error is False
    assert result.structured_content["starbase"] is None
    assert result.structured_content["id"] == _PLANET_WITHOUT_BASE_ID


def test_get_minefield_returns_whole_stored_entity(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    mcp, _, _ = _stored_turn_mcp(running_game_info, sample_turn)
    minefield = _minefield(sample_turn, _MINEFIELD_ID)

    result = call_tool(mcp, GET_MINEFIELD_TOOL, {**_SHELL, "minefield_id": _MINEFIELD_ID})

    assert result.is_error is False
    assert result.structured_content == dataclass_to_json(minefield)


def test_get_ion_storm_returns_whole_stored_entity(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    mcp, _, _ = _stored_turn_mcp(running_game_info, sample_turn)
    storm = _ion_storm(sample_turn, _ION_STORM_ID)

    result = call_tool(mcp, GET_ION_STORM_TOOL, {**_SHELL, "ion_storm_id": _ION_STORM_ID})

    assert result.is_error is False
    assert result.structured_content == dataclass_to_json(storm)


def test_get_wormhole_returns_whole_stored_entity(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    wormhole = Wormhole(
        id=7,
        x=10,
        y=20,
        name="A",
        targetx=30,
        targety=40,
        stability=80,
        turn=111,
    )
    turn = replace(sample_turn, wormholes=[wormhole])
    mcp, _, _ = _stored_turn_mcp(running_game_info, turn)

    result = call_tool(mcp, GET_WORMHOLE_TOOL, {**_SHELL, "wormhole_id": 7})

    assert result.is_error is False
    assert result.structured_content == dataclass_to_json(wormhole)


def test_get_player_strips_email_and_savekey(running_game_info: GameInfo, sample_turn: TurnInfo):
    player = replace(
        _player(sample_turn, _PLAYER_ID),
        email="secret@example.com",
        savekey="order-save-token",
    )
    turn = replace(
        sample_turn,
        players=[player if item.id == _PLAYER_ID else item for item in sample_turn.players],
    )
    mcp, _, _ = _stored_turn_mcp(running_game_info, turn)

    result = call_tool(mcp, GET_PLAYER_TOOL, {**_SHELL, "player_id": _PLAYER_ID})

    assert result.is_error is False
    expected = dataclass_to_json(player)
    for field in PLAYER_SECRET_FIELDS:
        expected.pop(field)
        assert field not in result.structured_content
    assert result.structured_content == expected
    assert result.structured_content["id"] == _PLAYER_ID
    assert result.structured_content["username"] == player.username


def test_get_player_uses_player_id_not_perspective(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    mcp, _, _ = _stored_turn_mcp(running_game_info, sample_turn)
    player = _player(sample_turn, _PLAYER_ID)

    result = call_tool(
        mcp,
        GET_PLAYER_TOOL,
        {"game_id": _GAME_ID, "turn": _TURN, "perspective": _PERSPECTIVE, "player_id": _PLAYER_ID},
    )

    assert result.is_error is False
    assert result.structured_content["id"] == player.id
    assert result.structured_content["id"] != _PERSPECTIVE


def test_missing_entity_ids_are_not_found(running_game_info: GameInfo, sample_turn: TurnInfo):
    mcp, _, _ = _stored_turn_mcp(running_game_info, sample_turn)
    missing = 99_999
    cases = (
        (GET_SHIP_TOOL, {"ship_id": missing}, "ship id"),
        (GET_PLANET_TOOL, {"planet_id": missing}, "planet id"),
        (GET_MINEFIELD_TOOL, {"minefield_id": missing}, "minefield id"),
        (GET_ION_STORM_TOOL, {"ion_storm_id": missing}, "ion storm id"),
        (GET_WORMHOLE_TOOL, {"wormhole_id": missing}, "wormhole id"),
        (GET_PLAYER_TOOL, {"player_id": missing}, "player id"),
    )

    for tool, extra, label in cases:
        result = call_tool(mcp, tool, {**_SHELL, **extra})
        assert result.is_error is True, tool
        assert f"No {label} {missing}" in result.content[0].text, tool


def test_fallback_tool_returns_needs_ensure_when_turn_missing(
    running_game_info: GameInfo,
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = False
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
    )

    result = call_tool(mcp, GET_SHIP_TOOL, {**_SHELL, "ship_id": _SHIP_ID})

    assert result.is_error is False
    assert result.structured_content == NEEDS_ENSURE_RESULT
    turns.get_turn_info.assert_not_called()


def test_fallback_tool_refuses_ineligible_perspective(
    running_game_info: GameInfo, sample_turn: TurnInfo
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = True
    turns.get_turn_info.return_value = sample_turn
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
    )

    result = call_tool(
        mcp,
        GET_PLANET_TOOL,
        {"game_id": _GAME_ID, "turn": _TURN, "perspective": 1, "planet_id": _PLANET_WITH_BASE_ID},
    )

    assert result.is_error is True
    text = result.content[0].text
    assert "Perspective 1 is not allowed" in text
    turns.is_turn_stored.assert_not_called()
    turns.get_turn_info.assert_not_called()
