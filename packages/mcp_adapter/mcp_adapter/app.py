"""Process MCP ASGI app for the root server to mount at /mcp."""

from __future__ import annotations

from mcp.server import MCPServer
from starlette.applications import Starlette

from mcp_adapter.server import build_mcp_server


def create_mcp_mount() -> tuple[MCPServer, Starlette]:
    """Return a new MCPServer and its Streamable HTTP app (path ``/`` under the mount)."""
    mcp = build_mcp_server()
    mcp_asgi = mcp.streamable_http_app(streamable_http_path="/")
    return mcp, mcp_asgi
