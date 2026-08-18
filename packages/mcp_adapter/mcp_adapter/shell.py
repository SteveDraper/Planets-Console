"""MCP shell tools: stored games, GameInfo, turn-ensure, stored perspectives."""

from collections.abc import Callable
from typing import Annotated, Any, Literal, TypedDict

from api.planets_nu import PlanetsNuClient
from api.serialization.game import game_info_to_json
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.transport.game_info_update import RefreshGameInfoParams
from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve

from mcp_adapter.eligibility import (
    eligible_perspectives_for_login,
    require_eligible_perspective,
)

LIST_STORED_GAMES_TOOL = "list_stored_games"
GET_GAME_INFO_TOOL = "get_game_info"
REFRESH_GAME_INFO_TOOL = "refresh_game_info"
ENSURE_TURN_TOOL = "ensure_turn"
LIST_STORED_PERSPECTIVES_TOOL = "list_stored_perspectives"

SHELL_TOOL_NAMES = (
    LIST_STORED_GAMES_TOOL,
    GET_GAME_INFO_TOOL,
    REFRESH_GAME_INFO_TOOL,
    ENSURE_TURN_TOOL,
    LIST_STORED_PERSPECTIVES_TOOL,
)

SHELL_TOOL_REQUIRED_PROPERTIES: dict[str, frozenset[str]] = {
    LIST_STORED_GAMES_TOOL: frozenset(),
    GET_GAME_INFO_TOOL: frozenset({"game_id"}),
    REFRESH_GAME_INFO_TOOL: frozenset({"game_id"}),
    ENSURE_TURN_TOOL: frozenset({"game_id", "turn", "perspective"}),
    LIST_STORED_PERSPECTIVES_TOOL: frozenset({"game_id", "turn"}),
}


class StoredGameEntry(TypedDict, total=False):
    id: str
    sectorName: str


class ListStoredGamesResult(TypedDict):
    games: list[StoredGameEntry]


class ListStoredPerspectivesResult(TypedDict):
    perspectives: list[int]


class EnsureTurnResult(TypedDict):
    status: Literal["already_stored", "loaded"]


def register_shell_tools(
    mcp: MCPServer,
    *,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
    planets_client_factory: Callable[[], PlanetsNuClient],
) -> None:
    """Register the v1 MCP shell tool catalog."""
    _register_list_stored_games(mcp, game_service, resolve_login)
    _register_get_game_info(mcp, game_service, resolve_login)
    _register_refresh_game_info(mcp, game_service, resolve_login, planets_client_factory)
    _register_ensure_turn(
        mcp,
        game_service,
        turn_load_service,
        resolve_login,
        planets_client_factory,
    )
    _register_list_stored_perspectives(mcp, game_service, turn_load_service, resolve_login)


def _login_params(login_identity: str) -> RefreshGameInfoParams:
    return RefreshGameInfoParams(username=login_identity, password=None)


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


def _register_get_game_info(
    mcp: MCPServer,
    game_service: GameService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=GET_GAME_INFO_TOOL)
    def get_game_info(
        game_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Return stored GameInfo for a game.

        Use refresh_game_info to fetch the latest document from Planets.nu.
        """
        _ = login
        return game_info_to_json(game_service.get_game_info(game_id))


def _register_refresh_game_info(
    mcp: MCPServer,
    game_service: GameService,
    resolve_login: Callable[[Context], str],
    planets_client_factory: Callable[[], PlanetsNuClient],
) -> None:
    @mcp.tool(name=REFRESH_GAME_INFO_TOOL)
    def refresh_game_info(
        game_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Refresh GameInfo from Planets.nu using the stored account API key.

        Password is not accepted on MCP; login exchange stays on the SPA/BFF path.
        """
        info = game_service.refresh_game_info(
            game_id,
            _login_params(login),
            planets_client_factory(),
        )
        return game_info_to_json(info)


def _register_ensure_turn(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
    planets_client_factory: Callable[[], PlanetsNuClient],
) -> None:
    @mcp.tool(name=ENSURE_TURN_TOOL)
    def ensure_turn(
        game_id: int,
        turn: int,
        perspective: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> EnsureTurnResult:
        """Load this shell-context turn from Planets.nu when it is not already stored.

        Returns already_stored or loaded only -- never the TurnInfo body.
        Synchronous: waits for loadturn. Other tools do not call this automatically.
        """
        require_eligible_perspective(
            game_service,
            login_identity=login,
            game_id=game_id,
            perspective=perspective,
        )
        if turn_load_service.is_turn_stored(game_id, perspective, turn):
            return {"status": "already_stored"}
        turn_load_service.ensure_turn_loaded(
            game_id,
            perspective,
            turn,
            _login_params(login),
            planets_client_factory(),
        )
        return {"status": "loaded"}


def _register_list_stored_perspectives(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=LIST_STORED_PERSPECTIVES_TOOL)
    def list_stored_perspectives(
        game_id: int,
        turn: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> ListStoredPerspectivesResult:
        """List perspective slots that already have this turn stored.

        Only slots allowed by viewpoint eligibility for this login are returned.
        """
        allowed = eligible_perspectives_for_login(
            game_service,
            login_identity=login,
            game_id=game_id,
        )
        stored = turn_load_service.list_stored_turn_perspectives(game_id, turn)
        return {"perspectives": [slot for slot in stored if slot in allowed]}
