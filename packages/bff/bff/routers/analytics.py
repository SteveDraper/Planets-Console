"""Analytics endpoints for the console shell.

Base map is a fixed layer derived from the Core API. Other analytics are placeholders.
All data routes require ``gameId``, ``turn``, and ``perspective`` query parameters so the
BFF can load turn-scoped analytics from Core (no hard-coded game context).
"""

from api.errors import PlanetsConsoleError
from api.services.game_service import GameService
from api.storage import get_storage
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

# type: "base" = always-on base map (planets + edges), not shown in analytics pane.
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
    game_id: int, perspective: int, turn_number: int, analytic_id: str
) -> dict:
    storage = get_storage()
    svc = GameService(storage)
    try:
        return svc.get_turn_analytics(game_id, perspective, turn_number, analytic_id)
    except PlanetsConsoleError as e:
        raise HTTPException(
            status_code=getattr(e, "http_error", 500),
            detail=str(e),
        ) from e


@router.get("")
def list_analytics():
    """Return analytics available to the console (placeholder list)."""
    return {"analytics": ANALYTICS_LIST}


@router.get("/{analytic_id}/table")
def get_analytic_table(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=1),
):
    """Placeholder tabular data (scoped for cache invalidation; same shape for now)."""
    _ = (game_id, turn, perspective)
    return {
        "analyticId": analytic_id,
        "columns": ["Col A", "Col B", "Col C"],
        "rows": [["a1", "b1", "c1"], ["a2", "b2", "c2"]],
    }


@router.get("/{analytic_id}/map")
def get_analytic_map(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=1),
):
    """Map data (nodes/edges). Base map = planets + connections; selectable analytics add overlays.

    Nodes use fixed Cartesian coordinates (x, y). Base map is always fetched first;
    selectable analytics contribute extra nodes/edges or (later) highlights.
    """
    if analytic_id == "base-map":
        return _turn_analytics_from_core(game_id, perspective, turn, "base-map")
    # Selectable analytics: placeholder 4-node square for now
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
