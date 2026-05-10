"""Temporary placeholder analytics."""

TABLE_METADATA = {
    "id": "placeholder-1",
    "name": "Placeholder Table",
    "supportsTable": True,
    "supportsMap": False,
    "type": "selectable",
}

MAP_METADATA = {
    "id": "placeholder-2",
    "name": "Placeholder Map",
    "supportsTable": False,
    "supportsMap": True,
    "type": "selectable",
}

BOTH_METADATA = {
    "id": "placeholder-3",
    "name": "Placeholder Both",
    "supportsTable": True,
    "supportsMap": True,
    "type": "selectable",
}


def get_table(analytic_id: str) -> dict:
    return {
        "analyticId": analytic_id,
        "columns": ["Col A", "Col B", "Col C"],
        "rows": [["a1", "b1", "c1"], ["a2", "b2", "c2"]],
    }


def get_map(analytic_id: str) -> dict:
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
