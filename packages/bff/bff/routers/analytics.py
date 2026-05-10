"""Analytics endpoints for the console shell."""

from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics, timed_section
from api.errors import PlanetsConsoleError
from api.services.game_service import GameService
from api.storage import get_storage
from fastapi import APIRouter, HTTPException, Query

from bff.analytics import (
    ANALYTICS_LIST,
    ConnectionsMapQuery,
    FlareConnectionMode,
    TurnScope,
    get_map_response,
    get_table_response,
    map_diagnostic_values,
    map_timing_section,
)
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)

router = APIRouter()


def _turn_analytics_from_core(
    game_id: int,
    perspective: int,
    turn_number: int,
    analytic_id: str,
    *,
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    **kwargs: object,
) -> dict:
    storage = get_storage()
    svc = GameService(storage)
    try:
        return svc.get_turn_analytics(
            game_id,
            perspective,
            turn_number,
            analytic_id,
            diagnostics=diagnostics,
            **kwargs,
        )
    except PlanetsConsoleError as e:
        raise HTTPException(
            status_code=getattr(e, "http_error", 500),
            detail=str(e),
        ) from e


@router.get("")
def list_analytics(
    include: IncludeDiagnostics = False,
):
    """Return analytics available to the console (placeholder list)."""
    body = {"analytics": ANALYTICS_LIST}
    root = optional_request_root(include, "GET", "/analytics", handler="list_analytics")
    with_timed_child(root, "list_analytics", "total", lambda: body)
    return finish_response(body, root)


@router.get("/{analytic_id}/table")
def get_analytic_table(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=1),
    include: IncludeDiagnostics = False,
):
    """Tabular data scoped to the selected game, turn, and perspective."""
    bff_path = f"/analytics/{analytic_id}/table"
    scope = TurnScope(game_id=game_id, perspective=perspective, turn=turn)

    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        handler="get_analytic_table",
    )
    table_node = root.child("get_analytic_table")
    with timed_section(table_node, "total"):
        body = get_table_response(analytic_id, scope, _turn_analytics_from_core, table_node)
    return finish_response(body, root)


@router.get("/{analytic_id}/map")
def get_analytic_map(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=1),
    warp_speed: int = Query(9, ge=1, le=9, alias="warpSpeed"),
    gravitonic_movement: bool = Query(False, alias="gravitonicMovement"),
    flare_mode: FlareConnectionMode = Query(FlareConnectionMode.OFF, alias="flareMode"),
    flare_depth: int = Query(
        1,
        ge=1,
        le=3,
        alias="flareDepth",
        description=(
            "Max hops (1–3) for mixed normal-move + flare paths; at least one hop must be a flare. "
            "Larger values add annulus pair candidates. Ignored when flareMode is off."
        ),
    ),
    include_illustrative_routes: bool = Query(
        False,
        alias="includeIllustrativeRoutes",
        description="When true, flare routes may include per-hop illustrativeRoute steps (Core).",
    ),
    include: IncludeDiagnostics = False,
):
    """Map data (nodes/edges). **base-map** returns planet nodes only (empty edges).

    **connections** returns route pairs for the SPA to draw as edges on those nodes.
    Other analytic ids return placeholder shapes until implemented.

    Nodes use fixed Cartesian coordinates (x, y). The SPA fetches base-map first, then
    enabled map analytics, and merges layers (see docs/design-connections-analytic.md).
    """
    bff_path = f"/analytics/{analytic_id}/map"

    scope = TurnScope(game_id=game_id, perspective=perspective, turn=turn)
    query = ConnectionsMapQuery(
        warp_speed=warp_speed,
        gravitonic_movement=gravitonic_movement,
        flare_mode=flare_mode,
        flare_depth=flare_depth,
        include_illustrative_routes=include_illustrative_routes,
    )
    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        **map_diagnostic_values(analytic_id, query),
        handler="get_analytic_map",
    )
    map_node = root.child("get_analytic_map")
    with timed_section(map_node, map_timing_section(analytic_id)):
        body = get_map_response(
            analytic_id,
            scope,
            query,
            _turn_analytics_from_core,
            map_node,
        )
    return finish_response(body, root)
