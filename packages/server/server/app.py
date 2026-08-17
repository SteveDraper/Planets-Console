"""Root FastAPI app: mounts Core API under /api, BFF under /bff, and MCP under /mcp.

In non-dev deployments you can serve the built frontend from this process:
set FRONTEND_DIST to the path to the frontend dist/ (e.g. packages/frontend/dist),
or run with that directory present; the app will serve static assets and SPA fallback.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from api.app import app as api_app
from api.services.seed import run_startup_seed_if_configured
from bff.app import app as bff_app
from bff.routers.diagnostics import recent_diagnostics_response
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from mcp_adapter.app import create_mcp_mount
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

# Starlette Mount("/mcp") only matches ``/mcp/...``, not ``/mcp``. Cursor's mcp.json URL is
# ``http://127.0.0.1:8000/mcp`` and Streamable HTTP clients often do not follow POST redirects.
_MCP_MOUNT_PATH = "/mcp"
_MCP_MOUNT_PATH_SLASH = "/mcp/"

# SPA catch-all is a GET path operation; without this exclusion it serves index.html for
# ``/mcp`` and ``/.well-known/oauth-protected-resource``, so Cursor fails tool discovery
# and exposes ``mcp_auth``.
_SPA_RESERVED_FIRST_SEGMENTS = frozenset(
    {
        "api",
        "bff",
        "mcp",
        "health",
        "diagnostics",
        ".well-known",
        "assets",
    }
)


class NormalizeMcpMountPath:
    """Rewrite ``/mcp`` to ``/mcp/`` so the Streamable HTTP mount sees the request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == _MCP_MOUNT_PATH:
            scope = dict(scope)
            scope["path"] = _MCP_MOUNT_PATH_SLASH
            if scope.get("raw_path") == b"/mcp":
                scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)


def _frontend_dist() -> Path | None:
    path = os.environ.get("FRONTEND_DIST")
    if path:
        p = Path(path)
    else:
        # Default: packages/frontend/dist relative to cwd (monorepo)
        p = Path("packages/frontend/dist")
    return p if p.is_dir() else None


def _spa_path_is_reserved(full_path: str) -> bool:
    first_segment = full_path.split("/", 1)[0]
    return first_segment in _SPA_RESERVED_FIRST_SEGMENTS


def create_app() -> FastAPI:
    """Build the root app. A new MCP session manager is created per call (tests)."""
    mcp, mcp_asgi = create_mcp_mount()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        run_startup_seed_if_configured()
        async with mcp.session_manager.run():
            yield

    root = FastAPI(
        title="Planets Console",
        lifespan=lifespan,
    )
    root.add_middleware(NormalizeMcpMountPath)
    root.mount("/api", api_app)
    root.mount("/bff", bff_app)
    root.mount("/mcp", mcp_asgi)

    @root.get("/diagnostics/recent", include_in_schema=False)
    def diagnostics_recent_mru_alias():
        """Same MRU buffer as ``GET /bff/diagnostics/recent`` (avoids depending on ``/bff`` when the
        dev proxy or a misconfigured backend returns 404 for the mounted path).
        """
        return recent_diagnostics_response()

    @root.get("/health")
    def health():
        return {"status": "ok"}

    # Optional: serve built frontend for single-server deployment
    frontend = _frontend_dist()
    if frontend is not None:
        assets = frontend / "assets"
        if assets.is_dir():
            root.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        index = frontend / "index.html"
        if index.is_file():

            @root.get("/")
            def _serve_index():
                return FileResponse(str(index))

            @root.get("/{full_path:path}")
            def _spa_fallback(full_path: str):
                if _spa_path_is_reserved(full_path):
                    raise HTTPException(status_code=404)
                return FileResponse(str(index))

    return root
