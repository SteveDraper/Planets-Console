"""In-process MCP server factory: tools-only catalog wrapping Core services."""

from collections.abc import Callable
from typing import Annotated, TypedDict

from api.services.credential_service import CredentialService
from api.services.game_service import GameService
from api.services.stack import build_default_service_stack
from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve

from mcp_adapter.identity import require_login_identity

LIST_STORED_GAMES_TOOL = "list_stored_games"

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


class StoredGameEntry(TypedDict, total=False):
    id: str
    sectorName: str


class ListStoredGamesResult(TypedDict):
    games: list[StoredGameEntry]


def _advertise_tools_only(mcp: MCPServer) -> None:
    """Remove prompt/resource handlers so discover does not advertise them."""
    handlers = mcp._lowlevel_server._request_handlers
    for method in _NON_TOOL_REQUEST_METHODS:
        handlers.pop(method, None)


def build_mcp_server(
    *,
    game_service: GameService | None = None,
    credential_service: CredentialService | None = None,
    resolve_login: Callable[[Context], str] | None = None,
) -> MCPServer:
    """Build an MCPServer with the tracer catalog (list_stored_games only)."""
    need_default_stack = game_service is None or (
        credential_service is None and resolve_login is None
    )
    if need_default_stack:
        stack = build_default_service_stack()
        if game_service is None:
            game_service = stack.games
        if credential_service is None:
            credential_service = stack.credentials

    login_resolver = resolve_login
    if login_resolver is None:
        if credential_service is None:
            raise TypeError("credential_service is required when resolve_login is omitted")

        def login_resolver(ctx: Context) -> str:
            return require_login_identity(ctx.headers, credential_service.probe)

    if game_service is None:
        raise TypeError("game_service is required")

    mcp = MCPServer("Planets Console MCP")
    _register_list_stored_games(mcp, game_service, login_resolver)
    _advertise_tools_only(mcp)
    return mcp


def _register_list_stored_games(
    mcp: MCPServer,
    game_service: GameService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=LIST_STORED_GAMES_TOOL)
    def list_stored_games(
        login: Annotated[str, Resolve(resolve_login)],
    ) -> ListStoredGamesResult:
        """List games stored on this console.

        Login identity is the HTTP header X-Planets-Nu-Login, not a tool argument.
        """
        _ = login
        return game_service.list_stored_games()
