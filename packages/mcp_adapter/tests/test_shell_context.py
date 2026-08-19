"""Stored-turn helpers for turn-scoped MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from api.errors import NotFoundError
from api.models.game import GameInfo
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from mcp_adapter.errors import ViewpointEligibilityRefusedError
from mcp_adapter.shell_context import (
    NEEDS_ENSURE_RESULT,
    load_stored_turn,
    planet_on_turn,
    ship_on_turn,
)

_GAME_ID = 628580
_TURN = 111


def test_load_stored_turn_returns_needs_ensure_without_fetching(
    running_game_info: GameInfo,
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = False

    result = load_stored_turn(
        games,
        turns,
        login_identity="arlowat",
        game_id=_GAME_ID,
        turn=_TURN,
        perspective=2,
    )

    assert result == NEEDS_ENSURE_RESULT
    turns.get_turn_info.assert_not_called()


def test_load_stored_turn_refuses_ineligible_perspective(running_game_info: GameInfo):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)

    with pytest.raises(ViewpointEligibilityRefusedError):
        load_stored_turn(
            games,
            turns,
            login_identity="arlowat",
            game_id=_GAME_ID,
            turn=_TURN,
            perspective=1,
        )

    turns.is_turn_stored.assert_not_called()


def test_planet_on_turn_and_ship_on_turn_raise_not_found():
    turn = MagicMock()
    turn.planets = []
    turn.ships = []

    with pytest.raises(NotFoundError, match="planet id 1"):
        planet_on_turn(turn, 1)
    with pytest.raises(NotFoundError, match="ship id 2"):
        ship_on_turn(turn, 2)
