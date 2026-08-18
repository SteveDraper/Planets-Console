"""Shared in-process MCP server helpers for adapter tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import MagicMock

from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from mcp.server.mcpserver import Context
from mcp_adapter.server import build_mcp_server


def run_coro(coro):
    return asyncio.run(coro)


def resolve_as(name: str) -> Callable[[Context], str]:
    def resolve_login(_ctx: Context) -> str:
        return name

    return resolve_login


def build_test_mcp(**overrides):
    """Build an MCP server with mocked Core services and a pinned login."""
    defaults = {
        "game_service": MagicMock(spec=GameService),
        "turn_load_service": MagicMock(spec=TurnLoadService),
        "resolve_login": resolve_as("alice"),
        "planets_client_factory": lambda: MagicMock(spec=PlanetsNuClient),
    }
    defaults.update(overrides)
    return build_mcp_server(**defaults)
