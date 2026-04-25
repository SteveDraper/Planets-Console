"""ASGI middleware: accept ``/bff/...`` when the BFF is run as the root app (e.g. uvicorn).

Vite and the full amalgamated server use the **logical** path ``/bff/...`` for the browser.
The latter mounts this app at ``/bff``, so routes see ``/analytics/...`` (prefix stripped). A
**standalone** BFF process receives the full ``/bff/...`` path and would otherwise 404. Strip
the prefix so the same client URLs work in both deployment modes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

# Starlette's ASGI types are loose here to avoid a starlette.typing import surface.
ASGIApp = Callable[[Any, Any, Any], Awaitable[None]]


class StripBffPrefixWhenRootApp:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket"):
            path = scope.get("path", "")
            if path.startswith("/bff/") or path == "/bff":
                new = path[4:] if path.startswith("/bff/") else "/"
                new_scope: dict = {**scope, "path": new}
                if "raw_path" in scope and isinstance(scope.get("raw_path"), (bytes, bytearray)):
                    new_scope["raw_path"] = new.encode("ascii")
                scope = new_scope
        await self.app(scope, receive, send)
