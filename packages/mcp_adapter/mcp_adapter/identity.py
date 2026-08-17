"""MCP login identity: HTTP header plus credential probe (fail closed)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from api.errors import ValidationError

from mcp_adapter.errors import LoginProbeFailedError, MissingLoginIdentityError

LOGIN_HEADER = "X-Planets-Nu-Login"


def login_header_value(headers: Mapping[str, str] | None) -> str | None:
    """Return the stripped MCP login identity from headers, or None if absent."""
    if headers is None:
        return None
    target = LOGIN_HEADER.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            stripped = str(value).strip()
            return stripped or None
    return None


def require_login_identity(
    headers: Mapping[str, str] | None,
    probe: Callable[[str], bool],
) -> str:
    """Return a probed MCP login identity, or raise an adapter error (fail closed)."""
    name = login_header_value(headers)
    if name is None:
        raise MissingLoginIdentityError(
            f"MCP login identity header {LOGIN_HEADER} is required. "
            "Set it on the client (e.g. PLANETS_NU_LOGIN in mcp.json)."
        )
    try:
        present = probe(name)
    except ValidationError as exc:
        raise LoginProbeFailedError(
            f"MCP login identity {name!r} failed credential probe."
        ) from exc
    if not present:
        raise LoginProbeFailedError(f"No stored account API key for MCP login identity {name!r}.")
    return name
