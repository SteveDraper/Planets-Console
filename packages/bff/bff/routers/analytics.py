"""Placeholder analytics endpoints for the console shell. No business logic."""
from fastapi import APIRouter

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

# Base map: planets (nodes) and connections (edges). Same shape as analytic map response.
BASE_MAP_NODES = [
    {"id": "p1", "label": "Planet 1", "x": 0, "y": 0},
    {"id": "p2", "label": "Planet 2", "x": 200, "y": 0},
    {"id": "p3", "label": "Planet 3", "x": 200, "y": 200},
    {"id": "p4", "label": "Planet 4", "x": 0, "y": 200},
]
BASE_MAP_EDGES = [
    {"source": "p1", "target": "p2"},
    {"source": "p2", "target": "p3"},
    {"source": "p3", "target": "p4"},
    {"source": "p4", "target": "p1"},
]


@router.get("")
def list_analytics():
    """Return analytics available to the console (placeholder list)."""
    return {"analytics": ANALYTICS_LIST}


@router.get("/{analytic_id}/table")
def get_analytic_table(analytic_id: str):
    """Placeholder tabular data for an analytic."""
    return {
        "analyticId": analytic_id,
        "columns": ["Col A", "Col B", "Col C"],
        "rows": [["a1", "b1", "c1"], ["a2", "b2", "c2"]],
    }


@router.get("/{analytic_id}/map")
def get_analytic_map(analytic_id: str):
    """Map data (nodes/edges). Base map = planets + connections; selectable analytics add overlays.

    Nodes use fixed Cartesian coordinates (x, y). Base map is always fetched first;
    selectable analytics contribute extra nodes/edges or (later) highlights.
    """
    if analytic_id == "base-map":
        return {
            "analyticId": analytic_id,
            "nodes": BASE_MAP_NODES,
            "edges": BASE_MAP_EDGES,
        }
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
