"""In-process MCP server factory: tools-only catalog wrapping Core services."""

from collections.abc import Callable

from api.planets_nu import PlanetsNuClient
from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from mcp_adapter.gameplay import (
    DISK_PROXIMITY_TOOL,
    DISTANCE_LY_TOOL,
    FLARE_ENDPOINTS_TOOL,
    GAMEPLAY_TOOL_NAMES,
    GAMEPLAY_TOOL_OPTIONAL_PROPERTIES,
    GAMEPLAY_TOOL_REQUIRED_PROPERTIES,
    HYPERJUMP_LANDING_TOOL,
    POINT_IN_WARP_WELL_TOOL,
    REACHABLE_PLANETS_TOOL,
    SAMPLE_STELLAR_CARTOGRAPHY_TOOL,
    STELLAR_CARTOGRAPHY_SUMMARY_TOOL,
    WARP_WELL_CELLS_TOOL,
    register_gameplay_tools,
)
from mcp_adapter.identity import require_login_identity
from mcp_adapter.shell import (
    ENSURE_TURN_TOOL,
    GET_GAME_INFO_TOOL,
    LIST_STORED_GAMES_TOOL,
    LIST_STORED_PERSPECTIVES_TOOL,
    REFRESH_GAME_INFO_TOOL,
    SHELL_TOOL_NAMES,
    SHELL_TOOL_REQUIRED_PROPERTIES,
    register_shell_tools,
)

# MCPServer always registers empty prompt/resource handlers. Dropping them is how
# server/discover stays tools-only.
_NON_TOOL_REQUEST_METHODS = (
    "prompts/list",
    "prompts/get",
    "resources/list",
    "resources/read",
    "resources/templates/list",
    "resources/subscribe",
    "resources/unsubscribe",
    "subscriptions/listen",
)


def _advertise_tools_only(mcp: MCPServer) -> None:
    """Remove prompt/resource handlers so discover does not advertise them."""
    handlers = mcp._lowlevel_server._request_handlers
    for method in _NON_TOOL_REQUEST_METHODS:
        handlers.pop(method, None)


def build_mcp_server(
    *,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    credential_service: CredentialService | None = None,
    resolve_login: Callable[[Context], str] | None = None,
    planets_client_factory: Callable[[], PlanetsNuClient] | None = None,
) -> MCPServer:
    """Build an MCPServer with the v1 MCP shell and named gameplay tool catalog."""
    if resolve_login is None:
        if credential_service is None:
            raise TypeError("credential_service is required when resolve_login is omitted")

        def login_resolver(ctx: Context) -> str:
            return require_login_identity(ctx.headers, credential_service.probe)
    else:
        login_resolver = resolve_login

    if planets_client_factory is None:
        planets_client_factory = PlanetsNuClient.from_config

    mcp = MCPServer("Planets Console MCP")
    register_shell_tools(
        mcp,
        game_service=game_service,
        turn_load_service=turn_load_service,
        resolve_login=login_resolver,
        planets_client_factory=planets_client_factory,
    )
    register_gameplay_tools(
        mcp,
        game_service=game_service,
        turn_load_service=turn_load_service,
        resolve_login=login_resolver,
    )
    _advertise_tools_only(mcp)
    return mcp


__all__ = [
    "DISK_PROXIMITY_TOOL",
    "DISTANCE_LY_TOOL",
    "ENSURE_TURN_TOOL",
    "FLARE_ENDPOINTS_TOOL",
    "GAMEPLAY_TOOL_NAMES",
    "GAMEPLAY_TOOL_OPTIONAL_PROPERTIES",
    "GAMEPLAY_TOOL_REQUIRED_PROPERTIES",
    "GET_GAME_INFO_TOOL",
    "HYPERJUMP_LANDING_TOOL",
    "LIST_STORED_GAMES_TOOL",
    "LIST_STORED_PERSPECTIVES_TOOL",
    "POINT_IN_WARP_WELL_TOOL",
    "REACHABLE_PLANETS_TOOL",
    "REFRESH_GAME_INFO_TOOL",
    "SAMPLE_STELLAR_CARTOGRAPHY_TOOL",
    "SHELL_TOOL_NAMES",
    "SHELL_TOOL_REQUIRED_PROPERTIES",
    "STELLAR_CARTOGRAPHY_SUMMARY_TOOL",
    "WARP_WELL_CELLS_TOOL",
    "build_mcp_server",
]
