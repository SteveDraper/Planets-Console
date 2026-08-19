"""In-process list_stored_games: login gate and GameService wrap mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

from api.services.game_service import GameService
from mcp import Client
from mcp_adapter.server import LIST_STORED_GAMES_TOOL, build_mcp_server

from tests.mcp_test_support import build_test_mcp, resolve_as, run_coro


def test_missing_login_is_adapter_error():
    games = MagicMock(spec=GameService)
    creds = MagicMock()
    creds.probe.return_value = True
    mcp = build_mcp_server(
        game_service=games,
        turn_load_service=MagicMock(),
        credential_service=creds,
        turn_analytic_service=MagicMock(),
    )

    async def body() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(LIST_STORED_GAMES_TOOL, {})
        assert result.is_error is True
        text = result.content[0].text
        assert "X-Planets-Nu-Login" in text
        games.list_stored_games.assert_not_called()

    run_coro(body())


def test_list_stored_games_wraps_game_service():
    games = MagicMock(spec=GameService)
    payload = {"games": [{"id": "628580", "sectorName": "Serada 9 Sector"}]}
    games.list_stored_games.return_value = payload
    mcp = build_test_mcp(game_service=games, resolve_login=resolve_as("alice"))

    async def body() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(LIST_STORED_GAMES_TOOL, {})
        assert result.is_error is False
        assert result.structured_content == payload
        games.list_stored_games.assert_called_once_with()

    run_coro(body())
