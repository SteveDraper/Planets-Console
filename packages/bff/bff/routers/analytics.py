"""Analytics endpoints for the console shell.

The **base-map** analytic is planet nodes only (no travel edges). The **connections** analytic
adds reachability routes separately. Other entries may be placeholders.
All data routes require ``gameId``, ``turn``, and ``perspective`` query parameters so the
BFF can load turn-scoped analytics from Core (no hard-coded game context).
"""

from collections.abc import Callable

from api.concepts.planet_connections import FlareConnectionMode
from api.diagnostics import DiagnosticNode, timed_section
from api.errors import PlanetsConsoleError
from api.services.game_service import GameService
from api.storage import get_storage
from fastapi import APIRouter, HTTPException, Query

from bff.diagnostics_dep import (
    IncludeDiagnostics,
    JSONScalar,
    finish_response,
    optional_request_root,
    with_timed_child,
)

router = APIRouter()

# type: "base" = always-on base map (planet nodes only; edges empty), not shown in analytics pane.
# type: "selectable" = user can enable/disable in the left bar.
ANALYTICS_LIST = [
    {
        "id": "base-map",
        "name": "Map",
        "supportsTable": False,
        "supportsMap": True,
        "type": "base",
    },
    {
        "id": "placeholder-1",
        "name": "Placeholder Table",
        "supportsTable": True,
        "supportsMap": False,
        "type": "selectable",
    },
    {
        "id": "connections",
        "name": "Connections",
        "supportsTable": False,
        "supportsMap": True,
        "type": "selectable",
    },
    {
        "id": "placeholder-2",
        "name": "Placeholder Map",
        "supportsTable": False,
        "supportsMap": True,
        "type": "selectable",
    },
    {
        "id": "placeholder-3",
        "name": "Placeholder Both",
        "supportsTable": True,
        "supportsMap": True,
        "type": "selectable",
    },
]


def _turn_analytics_from_core(
    game_id: int,
    perspective: int,
    turn_number: int,
    analytic_id: str,
    *,
    diagnostics: DiagnosticNode | None = None,
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
    """Placeholder tabular data (scoped for cache invalidation; same shape for now)."""
    bff_path = f"/analytics/{analytic_id}/table"

    def work() -> dict:
        return {
            "analyticId": analytic_id,
            "columns": ["Col A", "Col B", "Col C"],
            "rows": [["a1", "b1", "c1"], ["a2", "b2", "c2"]],
        }

    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        handler="get_analytic_table",
    )
    body = with_timed_child(root, "get_analytic_table", "total", work)
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
    flare_depth: int = Query(1, ge=1, le=3, alias="flareDepth"),
    include_illustrative_routes: bool = Query(False, alias="includeIllustrativeRoutes"),
    include: IncludeDiagnostics = False,
):
    """Map data (nodes/edges). **base-map** returns planet nodes only (empty edges).

    **connections** returns route pairs for the SPA to draw as edges on those nodes.
    Other analytic ids return placeholder shapes until implemented.

    Nodes use fixed Cartesian coordinates (x, y). The SPA fetches base-map first, then
    enabled map analytics, and merges layers (see docs/design-connections-analytic.md).
    """
    bff_path = f"/analytics/{analytic_id}/map"

    def run_with_diag(
        work: Callable[[], dict],
        *,
        section: str = "turn_analytics_from_core",
        **root_kw: JSONScalar,
    ) -> object:
        root = optional_request_root(include, "GET", bff_path, **root_kw)
        body = with_timed_child(root, "get_analytic_map", section, work)
        return finish_response(body, root)

    if analytic_id == "base-map":
        return run_with_diag(
            lambda: _turn_analytics_from_core(game_id, perspective, turn, "base-map"),
            gameId=game_id,
            turn=turn,
            perspective=perspective,
            handler="get_analytic_map",
        )
    if analytic_id == "connections":
        conn_common = {
            "connection_warp_speed": warp_speed,
            "connection_gravitonic_movement": gravitonic_movement,
            "connection_flare_mode": flare_mode,
            "connection_flare_depth": flare_depth,
            "connection_include_illustrative_routes": include_illustrative_routes,
        }
        root = optional_request_root(
            include,
            "GET",
            bff_path,
            gameId=game_id,
            turn=turn,
            perspective=perspective,
            warpSpeed=warp_speed,
            gravitonicMovement=gravitonic_movement,
            flareMode=str(flare_mode.value),
            flareDepth=flare_depth,
            includeIllustrativeRoutes=include_illustrative_routes,
            handler="get_analytic_map",
        )
        if root is None:
            body = _turn_analytics_from_core(
                game_id, perspective, turn, "connections", **conn_common
            )
        else:
            map_node = root.child("get_analytic_map")
            with timed_section(map_node, "turn_analytics_from_core"):
                body = _turn_analytics_from_core(
                    game_id,
                    perspective,
                    turn,
                    "connections",
                    diagnostics=map_node,
                    **conn_common,
                )
        return finish_response(body, root)
    # Selectable analytics: placeholder 4-node square for now

    def placeholder() -> dict:
        return {
            "analyticId": analytic_id,
            "nodes": [
                {"id": "n1", "label": "Node 1", "x": 0, "y": 0},
                {"id": "n2", "label": "Node 2", "x": 200, "y": 0},
                {"id": "n3", "label": "Node 3", "x": 200, "y": 200},
                {"id": "n4", "label": "Node 4", "x": 0, "y": 200},
            ],
            "edges": [
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3"},
                {"source": "n3", "target": "n4"},
                {"source": "n4", "target": "n1"},
            ],
        }

    return run_with_diag(
        placeholder,
        section="total",
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        handler="get_analytic_map",
    )
