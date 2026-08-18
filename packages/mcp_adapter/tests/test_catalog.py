"""In-process catalog lock for the v1 MCP shell tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mcp import Client
from mcp_adapter.server import (
    SHELL_TOOL_NAMES,
    SHELL_TOOL_REQUIRED_PROPERTIES,
    build_mcp_server,
)

from tests.mcp_test_support import build_test_mcp, run_coro


def test_catalog_locks_five_shell_tools_and_required_inputs():
    mcp = build_test_mcp()

    async def body() -> None:
        async with Client(mcp) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            assert names == list(SHELL_TOOL_NAMES)
            by_name = {tool.name: tool for tool in listed.tools}
            for name, required in SHELL_TOOL_REQUIRED_PROPERTIES.items():
                schema = by_name[name].input_schema
                properties = schema.get("properties", {})
                assert set(schema.get("required", [])) == set(required)
                assert set(properties) == set(required)
            assert client.server_capabilities is not None
            assert client.server_capabilities.tools is not None
            assert client.server_capabilities.prompts is None
            assert client.server_capabilities.resources is None

    run_coro(body())


def test_build_mcp_server_requires_game_service():
    with pytest.raises(TypeError, match="game_service"):
        build_mcp_server(
            turn_load_service=MagicMock(),
            credential_service=MagicMock(),
        )


def test_build_mcp_server_requires_turn_load_service():
    with pytest.raises(TypeError, match="turn_load_service"):
        build_mcp_server(
            game_service=MagicMock(),
            credential_service=MagicMock(),
        )


def test_build_mcp_server_requires_credential_service_or_resolve_login():
    with pytest.raises(TypeError, match="credential_service"):
        build_mcp_server(
            game_service=MagicMock(),
            turn_load_service=MagicMock(),
        )
