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
    ion_storm_on_turn,
    load_stored_turn,
    minefield_on_turn,
    planet_on_turn,
    player_on_turn,
    ship_on_turn,
    starbase_for_planet,
    wormhole_on_turn,
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


def test_named_entities_raise_not_found_when_absent():
    turn = MagicMock()
    turn.planets = []
    turn.ships = []
    turn.minefields = []
    turn.ionstorms = []
    turn.wormholes = []
    turn.players = []

    with pytest.raises(NotFoundError, match="planet id 1"):
        planet_on_turn(turn, 1)
    with pytest.raises(NotFoundError, match="ship id 2"):
        ship_on_turn(turn, 2)
    with pytest.raises(NotFoundError, match="minefield id 3"):
        minefield_on_turn(turn, 3)
    with pytest.raises(NotFoundError, match="ion storm id 4"):
        ion_storm_on_turn(turn, 4)
    with pytest.raises(NotFoundError, match="wormhole id 5"):
        wormhole_on_turn(turn, 5)
    with pytest.raises(NotFoundError, match="player id 6"):
        player_on_turn(turn, 6)


def test_starbase_for_planet_uses_planetid_not_rst_id():
    matching = MagicMock()
    matching.id = 1
    matching.planetid = 9
    decoy = MagicMock()
    decoy.id = 9
    decoy.planetid = 3
    turn = MagicMock()
    turn.starbases = [decoy, matching]

    assert starbase_for_planet(turn, 9) is matching
    assert starbase_for_planet(turn, 1) is None
