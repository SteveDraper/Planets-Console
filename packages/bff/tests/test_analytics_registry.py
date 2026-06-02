"""Tests for BFF analytics modules and registry dispatch."""

import pytest
from api.diagnostics import NOOP_DIAGNOSTICS
from api.transport.connections_options import derive_include_illustrative_routes
from bff.analytics import (
    ANALYTICS_LIST,
    ConnectionsMapQuery,
    FlareConnectionMode,
    TurnScope,
    get_map_response,
    get_table_response,
    map_diagnostic_values,
)
from bff.analytics.registry import REGISTERED_ANALYTICS
from bff.errors import BFFValidationError


def test_registered_analytics_have_unique_ids_and_handlers():
    ids = [descriptor.id for descriptor in REGISTERED_ANALYTICS]
    assert len(ids) == len(set(ids))
    for descriptor in REGISTERED_ANALYTICS:
        if descriptor.supports_table:
            assert descriptor.get_table is not None
        if descriptor.supports_map:
            assert descriptor.get_map is not None


def test_bff_descriptors_match_core_turn_analytics_registry():
    """BFF catalog ids must match Core TURN_ANALYTICS keys (both directions)."""
    from api.analytics.registry import TURN_ANALYTICS

    bff_ids = {descriptor.id for descriptor in REGISTERED_ANALYTICS}
    core_ids = set(TURN_ANALYTICS)
    assert bff_ids == core_ids, (
        f"Registry mismatch: BFF-only={sorted(bff_ids - core_ids)!r}, "
        f"Core-only={sorted(core_ids - bff_ids)!r}"
    )


def test_registry_metadata_keeps_scores_selectable_table_only():
    scores = next(a for a in ANALYTICS_LIST if a["id"] == "scores")
    assert scores["supportsTable"] is True
    assert scores["supportsMap"] is False


def test_registry_metadata_keeps_stellar_cartography_selectable_map_only():
    stellar = next(a for a in ANALYTICS_LIST if a["id"] == "stellar-cartography")
    assert stellar == {
        "id": "stellar-cartography",
        "name": "Stellar Cartography",
        "supportsTable": False,
        "supportsMap": True,
        "type": "selectable",
    }


def test_stellar_cartography_map_dispatch_forwards_to_core():
    calls = []

    def load_core(game_id, perspective, turn, analytic_id, **kwargs):
        calls.append((game_id, perspective, turn, analytic_id, kwargs))
        return {
            "analyticId": "stellar-cartography",
            "overlayCircles": [],
            "nodes": [],
            "edges": [],
            "meta": {"wormholeEdges": 0},
        }

    data = get_map_response(
        "stellar-cartography",
        TurnScope(628580, 1, 111),
        ConnectionsMapQuery(
            warp_speed=9,
            gravitonic_movement=False,
            flare_mode=FlareConnectionMode.OFF,
            flare_depth=1,
            include_illustrative_routes=False,
        ),
        load_core,
        NOOP_DIAGNOSTICS,
    )
    assert data["analyticId"] == "stellar-cartography"
    assert calls == [
        (
            628580,
            1,
            111,
            "stellar-cartography",
            {"diagnostics": NOOP_DIAGNOSTICS},
        )
    ]


def test_scores_table_dispatch_shapes_core_rows():
    def load_core(game_id, perspective, turn, analytic_id, **kwargs):
        assert (game_id, perspective, turn, analytic_id) == (628580, 1, 111, "scores")
        assert kwargs["diagnostics"] is NOOP_DIAGNOSTICS
        assert kwargs.get("include_military_score_inference") is False
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

    data = get_table_response("scores", TurnScope(628580, 1, 111), load_core, NOOP_DIAGNOSTICS)
    assert data["rows"][0] == [
        "The Solar Federation (sylk)",
        "76 (+1)",
        "23",
        "71 (-1)",
        "18 (-1)",
        "639101 (-1594)",
        "17",
    ]


def test_scores_table_dispatch_forwards_build_inference_to_core():
    calls = []

    def load_core(game_id, perspective, turn, analytic_id, **kwargs):
        calls.append((game_id, perspective, turn, analytic_id, kwargs))
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
                    "inference": {
                        "status": "exact",
                        "summary": "Best: Build Serpent Class Escort (empty)",
                        "solutionCount": 1,
                        "isComplete": True,
                        "solutions": [],
                        "diagnostics": {"catalog_size": 3},
                    },
                }
            ],
        }

    data = get_table_response(
        "scores",
        TurnScope(628580, 1, 111),
        load_core,
        NOOP_DIAGNOSTICS,
        include_build_inference=True,
    )
    assert data["includeBuildInference"] is True
    assert data["columns"][-1] == "Build inference"
    assert data["inferenceByRow"][0]["displayStatus"] == "success"
    assert calls[0][4]["include_military_score_inference"] is True


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


def test_include_illustrative_routes_spa_rule():
    assert derive_include_illustrative_routes(FlareConnectionMode.OFF, 3) is False
    assert derive_include_illustrative_routes(FlareConnectionMode.INCLUDE, 1) is False
    assert derive_include_illustrative_routes(FlareConnectionMode.INCLUDE, 2) is True
    assert derive_include_illustrative_routes(FlareConnectionMode.ONLY, 2) is True


def test_unknown_analytic_table_dispatch_raises_validation_error():
    scope = TurnScope(628580, 1, 111)
    with pytest.raises(BFFValidationError, match="Unknown analytic_id"):
        get_table_response("missing", scope, lambda *a, **k: {}, NOOP_DIAGNOSTICS)


def test_unsupported_table_mode_raises_validation_error():
    scope = TurnScope(628580, 1, 111)
    with pytest.raises(BFFValidationError, match="does not support table"):
        get_table_response("base-map", scope, lambda *a, **k: {}, NOOP_DIAGNOSTICS)
