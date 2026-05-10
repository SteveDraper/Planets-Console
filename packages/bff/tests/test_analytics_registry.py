"""Tests for BFF analytics modules and registry dispatch."""

from api.diagnostics import NOOP_DIAGNOSTICS
from bff.analytics import (
    ANALYTICS_LIST,
    ConnectionsMapQuery,
    FlareConnectionMode,
    TurnScope,
    get_map_response,
    get_table_response,
    map_diagnostic_values,
)


def test_registry_metadata_keeps_scores_selectable_table_only():
    scores = next(a for a in ANALYTICS_LIST if a["id"] == "scores")
    assert scores["supportsTable"] is True
    assert scores["supportsMap"] is False


def test_scores_table_dispatch_shapes_core_rows():
    def load_core(game_id, perspective, turn, analytic_id, **kwargs):
        assert (game_id, perspective, turn, analytic_id) == (628580, 1, 111, "scores")
        return {
            "analyticId": "scores",
            "rows": [
                {
                    "racePlayer": "The Solar Federation (sylk)",
                    "planets": {"value": 76, "change": 1},
                    "starbases": {"value": 23, "change": 0},
                    "warShips": {"value": 71, "change": -1},
                    "freighters": {"value": 18, "change": -1},
                    "military": {"value": 639101, "change": -1594},
                    "priorityPoints": {"value": 17, "change": 0},
                }
            ],
        }

    data = get_table_response("scores", TurnScope(628580, 1, 111), load_core)
    assert data["rows"][0] == [
        "The Solar Federation (sylk)",
        "76 (+1)",
        "23",
        "71 (-1)",
        "18 (-1)",
        "639101 (-1594)",
        "17",
    ]


def test_connections_map_dispatch_forwards_query_as_core_kwargs():
    calls = []

    def load_core(game_id, perspective, turn, analytic_id, **kwargs):
        calls.append((game_id, perspective, turn, analytic_id, kwargs))
        return {"analyticId": "connections", "nodes": [], "edges": [], "routes": []}

    query = ConnectionsMapQuery(
        warp_speed=8,
        gravitonic_movement=True,
        flare_mode=FlareConnectionMode.ONLY,
        flare_depth=2,
        include_illustrative_routes=True,
    )
    data = get_map_response(
        "connections",
        TurnScope(628580, 1, 111),
        query,
        load_core,
        NOOP_DIAGNOSTICS,
    )
    assert data["analyticId"] == "connections"
    _, _, _, analytic_id, kwargs = calls[0]
    assert analytic_id == "connections"
    assert kwargs["connection_warp_speed"] == 8
    assert kwargs["connection_gravitonic_movement"] is True
    assert kwargs["connection_flare_mode"] == "only"
    assert kwargs["connection_flare_depth"] == 2
    assert kwargs["connection_include_illustrative_routes"] is True


def test_connections_diagnostics_include_connection_query_values():
    query = ConnectionsMapQuery(
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=3,
        include_illustrative_routes=True,
    )
    assert map_diagnostic_values("connections", query) == {
        "warpSpeed": 9,
        "gravitonicMovement": False,
        "flareMode": "include",
        "flareDepth": 3,
        "includeIllustrativeRoutes": True,
    }
