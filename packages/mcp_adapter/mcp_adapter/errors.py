"""MCP adapter exceptions (tool errors the agent can read)."""


class McpAdapterError(Exception):
    """Adapter-level failure: identity, catalog breadth, or transport limits."""


class MissingLoginIdentityError(McpAdapterError):
    """MCP login identity header is missing or blank."""


class LoginProbeFailedError(McpAdapterError):
    """Credential probe failed closed for the named MCP login identity."""
