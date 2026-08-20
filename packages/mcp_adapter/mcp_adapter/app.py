"""Process MCP ASGI app for the root server to mount at /mcp."""

from __future__ import annotations

from api.planets_nu import PlanetsNuClient
from api.services.stack import get_process_service_stack
from mcp.server import MCPServer
from starlette.applications import Starlette

from mcp_adapter.server import build_mcp_server


def create_mcp_mount() -> tuple[MCPServer, Starlette]:
    """Return a new MCPServer and its Streamable HTTP app (path ``/`` under the mount)."""
    stack = get_process_service_stack()
    mcp = build_mcp_server(
        game_service=stack.games,
        turn_load_service=stack.turns,
        credential_service=stack.credentials,
        planets_client_factory=PlanetsNuClient.from_config,
        turn_analytic_service=stack.analytics,
    )
    mcp_asgi = mcp.streamable_http_app(streamable_http_path="/")
    return mcp, mcp_asgi
