"""In-process catalog lock for the v1 MCP shell and named gameplay tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mcp import Client
from mcp_adapter.server import (
    GAMEPLAY_TOOL_NAMES,
    GAMEPLAY_TOOL_OPTIONAL_PROPERTIES,
    GAMEPLAY_TOOL_REQUIRED_PROPERTIES,
    HYPERJUMP_LANDING_TOOL,
    SHELL_TOOL_NAMES,
    SHELL_TOOL_REQUIRED_PROPERTIES,
    build_mcp_server,
)

from tests.mcp_test_support import build_test_mcp, run_coro

_CATALOG_NAMES = list(SHELL_TOOL_NAMES) + list(GAMEPLAY_TOOL_NAMES)
_REQUIRED = {**SHELL_TOOL_REQUIRED_PROPERTIES, **GAMEPLAY_TOOL_REQUIRED_PROPERTIES}


def _optional_properties(name: str) -> frozenset[str]:
    return GAMEPLAY_TOOL_OPTIONAL_PROPERTIES.get(name, frozenset())


def _enum_values(schema: dict, name: str) -> set[str]:
    prop = schema["properties"][name]
    if "enum" in prop:
        return set(prop["enum"])
    items = prop.get("items")
    if isinstance(items, dict) and "enum" in items:
        return set(items["enum"])
    for alt in prop.get("anyOf", []) + prop.get("oneOf", []):
        if "enum" in alt:
            return set(alt["enum"])
        nested = alt.get("items")
        if isinstance(nested, dict) and "enum" in nested:
            return set(nested["enum"])
    raise AssertionError(f"no enum on {name}: {prop}")


def test_catalog_locks_shell_and_named_gameplay_tools_and_required_inputs():
    mcp = build_test_mcp()

    async def body() -> None:
        async with Client(mcp) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            assert names == _CATALOG_NAMES
            by_name = {tool.name: tool for tool in listed.tools}
            for name in _CATALOG_NAMES:
                schema = by_name[name].input_schema
                properties = schema.get("properties", {})
                required = _REQUIRED[name]
                optional = _optional_properties(name)
                assert set(schema.get("required", [])) == set(required)
                assert set(properties) == set(required | optional)
            well_kind = _enum_values(by_name["point_in_warp_well"].input_schema, "well_kind")
            assert well_kind == {"normal", "hyperjump"}
            assert _enum_values(by_name["warp_well_cells"].input_schema, "well_kind") == well_kind
            assert _enum_values(by_name["flare_endpoints"].input_schema, "movement_kind") == {
                "regular",
                "gravitonic",
            }
            assert _enum_values(by_name["disk_proximity"].input_schema, "include") == {
                "ships",
                "planets",
                "cartography",
            }
            assert _enum_values(by_name["reachable_planets"].input_schema, "flare_mode") == {
                "off",
                "include",
                "only",
            }
            reachable_required = by_name["reachable_planets"].input_schema.get("required", [])
            assert "include" not in by_name["disk_proximity"].input_schema.get("required", [])
            assert "flare_depth" not in reachable_required
            assert client.server_capabilities is not None
            assert client.server_capabilities.tools is not None
            assert client.server_capabilities.prompts is None
            assert client.server_capabilities.resources is None

    run_coro(body())


def test_hyperjump_landing_description_nudges_pre_well_snap():
    mcp = build_test_mcp()

    async def body() -> None:
        async with Client(mcp) as client:
            listed = await client.list_tools()
            by_name = {tool.name: tool for tool in listed.tools}
            description = by_name[HYPERJUMP_LANDING_TOOL].description
            assert "before warp-well snap" in description
            assert "point_in_warp_well" in description
            assert "warp_well_cells" in description

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
