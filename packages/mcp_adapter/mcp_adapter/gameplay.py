"""MCP named gameplay tools: thin wraps of Core game concepts."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from api.concepts.disk_proximity import DiskProximityHit
from api.concepts.disk_proximity import disk_proximity as query_disk_proximity
from api.concepts.flare_points import FlareMovementKind, flare_points_for_warp
from api.concepts.hyperjump import hyperjump_landing_xy, ship_is_performing_hyperjump
from api.concepts.planet_connections.connection_engine import connection_routes_with_options
from api.concepts.stellar_cartography.nebula_visibility import distance_ly as map_distance_ly
from api.concepts.stellar_cartography.sample_at import sample_at
from api.concepts.stellar_cartography.turn_summary import stellar_cartography_turn_summary
from api.concepts.turn_component_catalog import hulls_by_id
from api.concepts.warp_well import (
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
)
from api.models.flare_point import FlarePoint
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.transport.connections_options import FlareConnectionMode
from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve

from mcp_adapter.shell_context import (
    is_needs_ensure,
    load_stored_turn,
    planet_on_turn,
    ship_on_turn,
)

POINT_IN_WARP_WELL_TOOL = "point_in_warp_well"
WARP_WELL_CELLS_TOOL = "warp_well_cells"
FLARE_ENDPOINTS_TOOL = "flare_endpoints"
SAMPLE_STELLAR_CARTOGRAPHY_TOOL = "sample_stellar_cartography"
STELLAR_CARTOGRAPHY_SUMMARY_TOOL = "stellar_cartography_summary"
DISK_PROXIMITY_TOOL = "disk_proximity"
HYPERJUMP_LANDING_TOOL = "hyperjump_landing"
DISTANCE_LY_TOOL = "distance_ly"
REACHABLE_PLANETS_TOOL = "reachable_planets"

GAMEPLAY_TOOL_NAMES = (
    POINT_IN_WARP_WELL_TOOL,
    WARP_WELL_CELLS_TOOL,
    FLARE_ENDPOINTS_TOOL,
    SAMPLE_STELLAR_CARTOGRAPHY_TOOL,
    STELLAR_CARTOGRAPHY_SUMMARY_TOOL,
    DISK_PROXIMITY_TOOL,
    HYPERJUMP_LANDING_TOOL,
    DISTANCE_LY_TOOL,
    REACHABLE_PLANETS_TOOL,
)

SHELL_CONTEXT_PROPERTIES = frozenset({"game_id", "turn", "perspective"})

GAMEPLAY_TOOL_REQUIRED_PROPERTIES: dict[str, frozenset[str]] = {
    POINT_IN_WARP_WELL_TOOL: SHELL_CONTEXT_PROPERTIES
    | frozenset({"planet_id", "x", "y", "well_kind"}),
    WARP_WELL_CELLS_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"planet_id", "well_kind"}),
    FLARE_ENDPOINTS_TOOL: frozenset({"x", "y", "warp_speed", "movement_kind"}),
    SAMPLE_STELLAR_CARTOGRAPHY_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"x", "y"}),
    STELLAR_CARTOGRAPHY_SUMMARY_TOOL: SHELL_CONTEXT_PROPERTIES,
    DISK_PROXIMITY_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"x", "y", "radius_ly"}),
    HYPERJUMP_LANDING_TOOL: SHELL_CONTEXT_PROPERTIES | frozenset({"ship_id"}),
    DISTANCE_LY_TOOL: frozenset({"x1", "y1", "x2", "y2"}),
    REACHABLE_PLANETS_TOOL: SHELL_CONTEXT_PROPERTIES
    | frozenset({"from_planet_id", "warp_speed", "gravitonic_movement", "flare_mode"}),
}

GAMEPLAY_TOOL_OPTIONAL_PROPERTIES: dict[str, frozenset[str]] = {
    POINT_IN_WARP_WELL_TOOL: frozenset(),
    WARP_WELL_CELLS_TOOL: frozenset(),
    FLARE_ENDPOINTS_TOOL: frozenset(),
    SAMPLE_STELLAR_CARTOGRAPHY_TOOL: frozenset(),
    STELLAR_CARTOGRAPHY_SUMMARY_TOOL: frozenset(),
    DISK_PROXIMITY_TOOL: frozenset({"include"}),
    HYPERJUMP_LANDING_TOOL: frozenset(),
    DISTANCE_LY_TOOL: frozenset(),
    REACHABLE_PLANETS_TOOL: frozenset({"flare_depth"}),
}

HYPERJUMP_NOT_JUMPING_REASON = "Ship is not performing a hyperjump."

WellKindArg = Literal["normal", "hyperjump"]
MovementKindArg = Literal["regular", "gravitonic"]
FlareModeArg = Literal["off", "include", "only"]
DiskIncludeArg = Literal["ships", "planets", "cartography"]


def register_gameplay_tools(
    mcp: MCPServer,
    *,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    """Register the v1 MCP named gameplay tools that wrap Core concepts."""
    _register_point_in_warp_well(mcp, game_service, turn_load_service, resolve_login)
    _register_warp_well_cells(mcp, game_service, turn_load_service, resolve_login)
    _register_flare_endpoints(mcp, resolve_login)
    _register_sample_stellar_cartography(mcp, game_service, turn_load_service, resolve_login)
    _register_stellar_cartography_summary(mcp, game_service, turn_load_service, resolve_login)
    _register_disk_proximity(mcp, game_service, turn_load_service, resolve_login)
    _register_hyperjump_landing(mcp, game_service, turn_load_service, resolve_login)
    _register_distance_ly(mcp, resolve_login)
    _register_reachable_planets(mcp, game_service, turn_load_service, resolve_login)


def _load_turn(
    game_service: GameService,
    turn_load_service: TurnLoadService,
    *,
    login: str,
    game_id: int,
    turn: int,
    perspective: int,
):
    return load_stored_turn(
        game_service,
        turn_load_service,
        login_identity=login,
        game_id=game_id,
        turn=turn,
        perspective=perspective,
    )


def _map_cells(cells: list[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"x": gx, "y": gy} for gx, gy in cells]


def _flare_map_endpoints(
    origin_x: int,
    origin_y: int,
    points: list[FlarePoint],
) -> list[dict[str, dict[str, int]]]:
    endpoints: list[dict[str, dict[str, int]]] = []
    for point in points:
        wx, wy = point.waypoint_offset
        ax, ay = point.arrival_offset
        dx, dy = point.direct_aim_arrival_offset
        endpoints.append(
            {
                "waypoint": {"x": origin_x + wx, "y": origin_y + wy},
                "arrival": {"x": origin_x + ax, "y": origin_y + ay},
                "direct_aim_arrival": {"x": origin_x + dx, "y": origin_y + dy},
            }
        )
    return endpoints


def _disk_hit_to_json(hit: DiskProximityHit) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": hit.kind, "id": hit.id, "x": hit.x, "y": hit.y}
    if hit.radius is not None:
        payload["radius"] = hit.radius
    return payload


def _routes_from_planet(routes: list[dict[str, Any]], from_planet_id: int) -> list[dict[str, Any]]:
    return [
        route
        for route in routes
        if route.get("fromPlanetId") == from_planet_id or route.get("toPlanetId") == from_planet_id
    ]


def _register_point_in_warp_well(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=POINT_IN_WARP_WELL_TOOL)
    def point_in_warp_well(
        game_id: int,
        turn: int,
        perspective: int,
        planet_id: int,
        x: float,
        y: float,
        well_kind: WellKindArg,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Whether map point (x, y) lies in this planet's warp well.

        well_kind selects normal (Euclidean 3 ly) or hyperjump (exclusive radius 3) geometry.
        Prefer this over scanning TurnInfo. Debris-disk planets have no well.
        """
        loaded = _load_turn(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
        )
        if is_needs_ensure(loaded):
            return loaded
        planet = planet_on_turn(loaded, planet_id)
        inside = coordinate_in_warp_well(planet, x, y, WarpWellKind(well_kind))
        return {"inside": inside}


def _register_warp_well_cells(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=WARP_WELL_CELLS_TOOL)
    def warp_well_cells(
        game_id: int,
        turn: int,
        perspective: int,
        planet_id: int,
        well_kind: WellKindArg,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Enumerate integer map cells whose centers lie in this planet's warp well.

        well_kind selects normal or hyperjump geometry. Debris-disk planets return no cells.
        """
        loaded = _load_turn(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
        )
        if is_needs_ensure(loaded):
            return loaded
        planet = planet_on_turn(loaded, planet_id)
        cells = map_cell_indices_in_warp_well(planet, WarpWellKind(well_kind))
        return {"cells": _map_cells(cells)}


def _register_flare_endpoints(
    mcp: MCPServer,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=FLARE_ENDPOINTS_TOOL)
    def flare_endpoints(
        x: int,
        y: int,
        warp_speed: int,
        movement_kind: MovementKindArg,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Map-absolute evasion flare endpoints from origin (x, y) at this warp.

        Returns waypoint, arrival, and direct-aim arrival cells -- not raw offsets.
        movement_kind is regular or gravitonic. Login only; no turn is required.
        """
        _ = login
        points = flare_points_for_warp(warp_speed, FlareMovementKind(movement_kind))
        return {"endpoints": _flare_map_endpoints(x, y, points)}


def _register_sample_stellar_cartography(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=SAMPLE_STELLAR_CARTOGRAPHY_TOOL)
    def sample_stellar_cartography(
        game_id: int,
        turn: int,
        perspective: int,
        x: int,
        y: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Stacked Stellar Cartography features at map cell (x, y).

        Prefer this point sample over scanning TurnInfo nebulae, storms, clusters, and holes.
        """
        loaded = _load_turn(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
        )
        if is_needs_ensure(loaded):
            return loaded
        return sample_at(loaded, x, y)


def _register_stellar_cartography_summary(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=STELLAR_CARTOGRAPHY_SUMMARY_TOOL)
    def stellar_cartography_summary(
        game_id: int,
        turn: int,
        perspective: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Lightweight Stellar Cartography facts for this stored turn.

        Counts ion storms and whether Nu ion storms are enabled. Not a full map sample.
        """
        loaded = _load_turn(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
        )
        if is_needs_ensure(loaded):
            return loaded
        return stellar_cartography_turn_summary(loaded)


def _register_disk_proximity(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=DISK_PROXIMITY_TOOL)
    def disk_proximity(
        game_id: int,
        turn: int,
        perspective: int,
        x: float,
        y: float,
        radius_ly: float,
        login: Annotated[str, Resolve(resolve_login)],
        include: list[DiskIncludeArg] | None = None,
    ) -> dict[str, Any]:
        """Ships, planets, and cartography features within radius_ly of (x, y).

        Omit include to search all three families. Repeat include to restrict to
        ships, planets, and/or cartography. Hits include kind, id, x, y, and radius
        when the feature is a disk. Minefields are not in this result set.
        """
        loaded = _load_turn(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
        )
        if is_needs_ensure(loaded):
            return loaded
        hits = query_disk_proximity(loaded, x, y, radius_ly, include=include)
        return {"hits": [_disk_hit_to_json(hit) for hit in hits]}


def _register_hyperjump_landing(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=HYPERJUMP_LANDING_TOOL)
    def hyperjump_landing(
        game_id: int,
        turn: int,
        perspective: int,
        ship_id: int,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Estimated HYP landing for this ship before warp-well snap.

        The returned point is the hyperjump landing before warp-well snap. It does
        not pull the ship into a nearby planet well. After you have the landing,
        consider well pull via point_in_warp_well and warp_well_cells (hyperjump
        well_kind) around nearby planets.
        """
        loaded = _load_turn(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
        )
        if is_needs_ensure(loaded):
            return loaded
        ship = ship_on_turn(loaded, ship_id)
        hull = hulls_by_id(loaded).get(ship.hullid)
        if not ship_is_performing_hyperjump(ship, hull):
            return {"jumping": False, "reason": HYPERJUMP_NOT_JUMPING_REASON}
        land_x, land_y = hyperjump_landing_xy(ship)
        return {"jumping": True, "x": land_x, "y": land_y}


def _register_distance_ly(
    mcp: MCPServer,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=DISTANCE_LY_TOOL)
    def distance_ly(
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        login: Annotated[str, Resolve(resolve_login)],
    ) -> dict[str, Any]:
        """Euclidean map distance in light-years between two points.

        Login only; no turn is required. 1 map unit is 1 ly.
        """
        _ = login
        return {"distance_ly": map_distance_ly(x1, y1, x2, y2)}


def _register_reachable_planets(
    mcp: MCPServer,
    game_service: GameService,
    turn_load_service: TurnLoadService,
    resolve_login: Callable[[Context], str],
) -> None:
    @mcp.tool(name=REACHABLE_PLANETS_TOOL)
    def reachable_planets(
        game_id: int,
        turn: int,
        perspective: int,
        from_planet_id: int,
        warp_speed: int,
        gravitonic_movement: bool,
        flare_mode: FlareModeArg,
        login: Annotated[str, Resolve(resolve_login)],
        flare_depth: int = 1,
    ) -> dict[str, Any]:
        """One-turn planet-pair reachability from from_planet_id.

        Wraps the Connections engine and keeps routes where from_planet_id is an
        endpoint. Origin is a planet id only -- not an arbitrary map coordinate.
        No illustrative routes. flare_depth defaults to 1 (1--3) when flares are on.
        """
        loaded = _load_turn(
            game_service,
            turn_load_service,
            login=login,
            game_id=game_id,
            turn=turn,
            perspective=perspective,
        )
        if is_needs_ensure(loaded):
            return loaded
        planet_on_turn(loaded, from_planet_id)
        outcome = connection_routes_with_options(
            loaded.planets,
            warp_speed=warp_speed,
            gravitonic_movement=gravitonic_movement,
            flare_mode=FlareConnectionMode(flare_mode),
            flare_depth=flare_depth,
            include_illustrative_routes=False,
        )
        return {"routes": _routes_from_planet(outcome.routes, from_planet_id)}
