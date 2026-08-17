"""In-process catalog lock for the MCP tracer (list_stored_games only)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from mcp import Client
from mcp_adapter.server import LIST_STORED_GAMES_TOOL, build_mcp_server


def test_catalog_includes_list_stored_games_only():
    mcp = build_mcp_server(
        game_service=MagicMock(),
        credential_service=MagicMock(),
    )

    async def body() -> None:
        async with Client(mcp) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            assert names == [LIST_STORED_GAMES_TOOL]
            schema = listed.tools[0].input_schema
            assert schema.get("properties", {}) == {}
            assert client.server_capabilities is not None
            assert client.server_capabilities.tools is not None
            assert client.server_capabilities.prompts is None
            assert client.server_capabilities.resources is None

    asyncio.run(body())
