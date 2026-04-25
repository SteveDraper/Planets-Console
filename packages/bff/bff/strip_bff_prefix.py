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


def _raw_path_after_strip_bff(new_path: str, previous_raw: bytes | bytearray | None) -> bytes:
    """Match ``raw_path`` to the stripped ``path`` without assuming ASCII or re-encoding the tail.

    Prefer slicing the existing ``/bff`` prefix from ``scope["raw_path"]`` so percent-bytes
    in the rest of the path are preserved. Fall back to UTF-8 for ``new_path`` when the raw
    form does not start with a literal ``b"/bff"`` (e.g. different encoding of ``bff``).
    """
    if previous_raw is None:
        return new_path.encode("utf-8")
    b = bytes(previous_raw)
    if b.startswith(b"/bff/"):
        return b[4:]
    if b == b"/bff":
        return b"/"
    return new_path.encode("utf-8")


class StripBffPrefixWhenRootApp:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket"):
            path = scope.get("path", "")
            if path.startswith("/bff/") or path == "/bff":
                new = path[4:] if path.startswith("/bff/") else "/"
                new_scope: dict = {**scope, "path": new}
                rp = scope.get("raw_path")
                if isinstance(rp, (bytes, bytearray)) or rp is None:
                    new_scope["raw_path"] = _raw_path_after_strip_bff(
                        new, rp if isinstance(rp, (bytes, bytearray)) else None
                    )
                else:
                    new_scope["raw_path"] = new.encode("utf-8")
                scope = new_scope
        await self.app(scope, receive, send)
