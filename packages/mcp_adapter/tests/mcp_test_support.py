"""Shared in-process MCP server helpers for adapter tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from unittest.mock import MagicMock

from api.analytics.export_context import make_analytic_query_context
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import GameInfo
from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_load_service import TurnLoadService
from mcp import Client
from mcp.server.mcpserver import Context
from mcp_adapter.server import build_mcp_server


def run_coro(coro):
    return asyncio.run(coro)


def resolve_as(name: str) -> Callable[[Context], str]:
    def resolve_login(_ctx: Context) -> str:
        return name

    return resolve_login


def call_tool(mcp, name: str, arguments: dict):
    async def body():
        async with Client(mcp) as client:
            return await client.call_tool(name, arguments)

    return run_coro(body())


def stub_turn_analytic_service(turn_load_service: TurnLoadService) -> MagicMock:
    """TurnAnalyticService whose export_query_context delegates to Core's factory."""
    analytics = MagicMock(spec=TurnAnalyticService)

    def export_query_context(
        game_id: int,
        perspective: int,
        turn_number: int,
        *,
        username: str = "",
        export_registry: Mapping[str, AnalyticExportCatalog] | None = None,
    ):
        _ = username
        turn = turn_load_service.get_turn_info(game_id, perspective, turn_number)
        return make_analytic_query_context(
            turn,
            TurnAnalyticsOptions(),
            game_id=game_id,
            perspective=perspective,
            export_registry=export_registry,
        )

    analytics.export_query_context.side_effect = export_query_context
    return analytics


def build_test_mcp(**overrides):
    """Build an MCP server with mocked Core services and a pinned login."""
    defaults = {
        "game_service": MagicMock(spec=GameService),
        "turn_load_service": MagicMock(spec=TurnLoadService),
        "resolve_login": resolve_as("alice"),
        "planets_client_factory": lambda: MagicMock(spec=PlanetsNuClient),
    }
    defaults.update(overrides)
    if "turn_analytic_service" not in defaults:
        defaults["turn_analytic_service"] = stub_turn_analytic_service(
            defaults["turn_load_service"]
        )
    return build_mcp_server(**defaults)


def stored_turn_mcp(running_game_info: GameInfo, turn: object, *, login: str = "arlowat"):
    """MCP server whose TurnLoadService already has this turn stored."""
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
