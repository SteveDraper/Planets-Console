"""MCP TurnInfo fallback tools: whole stored entity for a named id."""

from collections.abc import Callable
from typing import Annotated, Any

from api.models.game import TurnInfo
from api.models.planet import Planet
from api.models.player import Player
from api.serialization.codecs import dataclass_to_json
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve

from mcp_adapter.shell_context import (
    SHELL_CONTEXT_PROPERTIES,
    ion_storm_on_turn,
    is_needs_ensure,
    load_stored_turn,
    minefield_on_turn,
    planet_on_turn,
    player_on_turn,
    ship_on_turn,
    starbase_for_planet,
    wormhole_on_turn,
)

GET_SHIP_TOOL = "get_ship"
GET_PLANET_TOOL = "get_planet"
GET_MINEFIELD_TOOL = "get_minefield"
GET_ION_STORM_TOOL = "get_ion_storm"
GET_WORMHOLE_TOOL = "get_wormhole"
GET_PLAYER_TOOL = "get_player"

FALLBACK_TOOL_NAMES = (
    GET_SHIP_TOOL,
    GET_PLANET_TOOL,
    GET_MINEFIELD_TOOL,
    GET_ION_STORM_TOOL,
    GET_WORMHOLE_TOOL,
    GET_PLAYER_TOOL,
)

FALLBACK_TOOL_REQUIRED_PROPERTIES: dict[str, frozenset[str]] = {
    GET_SHIP_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"ship_id"}),
    GET_PLANET_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"planet_id"}),
    GET_MINEFIELD_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"minefield_id"}),
    GET_ION_STORM_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"ion_storm_id"}),
    GET_WORMHOLE_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"wormhole_id"}),
    GET_PLAYER_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"player_id"}),
}

FALLBACK_TOOL_OPTIONAL_PROPERTIES: dict[str, frozenset[str]] = {
    name: frozenset() for name in FALLBACK_TOOL_NAMES
}

PLAYER_SECRET_FIELDS = ("email", "savekey")


def register_turninfo_fallback_tools(
    mcp: MCPServer,
    *,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    """Register named TurnInfo entity reads for this perspective's RST."""
    _register_get_ship(mcp, game_service, turn_load_service, resolve_login)
    _register_get_planet(mcp, game_service, turn_load_service, resolve_login)
    _register_get_minefield(mcp, game_service, turn_load_service, resolve_login)
    _register_get_ion_storm(mcp, game_service, turn_load_service, resolve_login)
    _register_get_wormhole(mcp, game_service, turn_load_service, resolve_login)
    _register_get_player(mcp, game_service, turn_load_service, resolve_login)


def _json_entity(_turn: TurnInfo, entity: object) -> dict[str, Any]:
    return dataclass_to_json(entity)


def _named_entity_payload(
    game_service: GameService,
    turn_load_service: TurnLoadService,
    *,
    login: str,
    game_id: int,
    turn: int,
    perspective: int,
    lookup: Callable[[TurnInfo, int], Any],
    entity_id: int,
    dump: Callable[[TurnInfo, Any], dict[str, Any]] = _json_entity,
) -> dict[str, Any]:
    """Load stored turn, then dump the named entity (or return needs_ensure)."""
    loaded = load_stored_turn(
        game_service,
        turn_load_service,
        login_identity=login,
        game_id=game_id,
        turn=turn,
        perspective=perspective,
    )
    if is_needs_ensure(loaded):
        return loaded
    return dump(loaded, lookup(loaded, entity_id))


def _planet_with_starbase(turn: TurnInfo, planet: Planet) -> dict[str, Any]:
    payload = dataclass_to_json(planet)
    starbase = starbase_for_planet(turn, planet.id)
    payload["starbase"] = dataclass_to_json(starbase) if starbase is not None else None
    return payload


def _player_without_secrets(_turn: TurnInfo, player: Player) -> dict[str, Any]:
    payload = dataclass_to_json(player)
    for field in PLAYER_SECRET_FIELDS:
        payload.pop(field, None)
    return payload


def _register_get_ship(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=GET_SHIP_TOOL)
    def get_ship(
        game_id: int,
        turn: int,
        perspective: int,
        ship_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Return this perspective's stored TurnInfo ship for ship_id.

        Last-resort named-object fields (friendly code, cargo, mission). Prefer
        disk_proximity for nearby ships and hyperjump_landing for a HYP landing.
        Not a list, search, or filter.
        """
        return _named_entity_payload(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            lookup=ship_on_turn,
            entity_id=ship_id,
        )


def _register_get_planet(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=GET_PLANET_TOOL)
    def get_planet(
        game_id: int,
        turn: int,
        perspective: int,
        planet_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Return this perspective's stored TurnInfo planet for planet_id.

        Includes starbase when one orbits this planet, looked up by planet id
        rather than RST starbase.id. buildingstarbase stays on the planet.
        Prefer disk_proximity, warp-well tools, and reachable_planets when those
        answer the question. Not a list, search, or filter.
        """
        return _named_entity_payload(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            lookup=planet_on_turn,
            entity_id=planet_id,
            dump=_planet_with_starbase,
        )


def _register_get_minefield(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=GET_MINEFIELD_TOOL)
    def get_minefield(
        game_id: int,
        turn: int,
        perspective: int,
        minefield_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Return this perspective's stored TurnInfo minefield for minefield_id.

        Minefields are not in disk_proximity. Use this for named-object fields
        when you already have the id. Not a list, search, geometry, or filter.
        """
        return _named_entity_payload(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            lookup=minefield_on_turn,
            entity_id=minefield_id,
        )


def _register_get_ion_storm(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=GET_ION_STORM_TOOL)
    def get_ion_storm(
        game_id: int,
        turn: int,
        perspective: int,
        ion_storm_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Return this perspective's stored TurnInfo ion storm for ion_storm_id.

        Prefer sample_stellar_cartography, stellar_cartography_summary, and
        disk_proximity cartography hits when those answer the question.
        Not a list, search, or filter.
        """
        return _named_entity_payload(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            lookup=ion_storm_on_turn,
            entity_id=ion_storm_id,
        )


def _register_get_wormhole(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=GET_WORMHOLE_TOOL)
    def get_wormhole(
        game_id: int,
        turn: int,
        perspective: int,
        wormhole_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Return this perspective's stored TurnInfo wormhole for wormhole_id.

        Prefer sample_stellar_cartography and disk_proximity cartography hits.
        Not a list, search, or filter.
        """
        return _named_entity_payload(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            lookup=wormhole_on_turn,
            entity_id=wormhole_id,
        )


def _register_get_player(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=GET_PLAYER_TOOL)
    def get_player(
        game_id: int,
        turn: int,
        perspective: int,
        player_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Return this perspective's stored TurnInfo player for player_id.

        player_id is Player.id, not the perspective slot. email and savekey are
        omitted. Not a list, search, or filter.
        """
        return _named_entity_payload(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
            lookup=player_on_turn,
            entity_id=player_id,
            dump=_player_without_secrets,
        )
