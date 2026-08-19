"""MCP adapter exceptions (tool errors the agent can read)."""


class McpAdapterError(Exception):
    """Adapter-level failure: identity, catalog breadth, or transport limits."""


class MissingLoginIdentityError(McpAdapterError):
    """MCP login identity header is missing or blank."""


class LoginProbeFailedError(McpAdapterError):
    """Credential probe failed closed for the named MCP login identity."""


class ViewpointEligibilityRefusedError(McpAdapterError):
    """Named perspective is outside the login's viewpoint eligibility set."""

    def __init__(self, *, game_id: int, perspective: int, login_identity: str) -> None:
        self.game_id = game_id
        self.perspective = perspective
        self.login_identity = login_identity
        super().__init__(
            f"Perspective {perspective} is not allowed for MCP login identity "
            f"{login_identity!r} in game {game_id}."
        )


class CatalogTooBroadError(McpAdapterError):
    """Omit-id list_analytic_exports with detail=full is refused."""

    def __init__(self) -> None:
        super().__init__(
            "detail=full requires analytic_id; omit-id lists MCP export catalog summaries only."
        )


class EmptyHatchPathsError(McpAdapterError):
    """query_analytic_export requires a non-empty paths list."""

    def __init__(self) -> None:
        super().__init__("paths must be a non-empty list of JSONPath selectors.")
