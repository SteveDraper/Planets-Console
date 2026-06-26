"""Unit tests for BFF analytics routes. Verify response shape and map node coordinates."""

import copy
import json
import math
from pathlib import Path

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.storage import clear_backend_cache, get_storage
from bff.analytics import ANALYTICS_LIST
from bff.app import app
from bff.core_client import clear_core_client_cache
from fastapi.testclient import TestClient

client = TestClient(app)

SCOPE_QS = "gameId=628580&turn=111&perspective=1"

REPO_PACKAGES_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = REPO_PACKAGES_DIR / "api" / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _setup_storage_for_core_calls():
    """Seed Core storage so BFF can call Core via ASGI transport."""
    clear_backend_cache()
    clear_core_client_cache()
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    storage = get_storage()
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        storage.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        turn_rst = json.load(f)
        for turn_number in range(1, 112):
            turn_data = copy.deepcopy(turn_rst)
            turn_data["settings"]["turn"] = turn_number
            turn_data["game"]["turn"] = turn_number
            storage.put(f"games/628580/1/turns/{turn_number}", turn_data)
    yield
    clear_backend_cache()
    clear_core_client_cache()


def test_list_analytics_returns_analytics_list():
    """GET /analytics returns list of analytics with expected fields."""
    response = client.get("/analytics")
    assert response.status_code == 200
    data = response.json()
    assert "analytics" in data
    analytics = data["analytics"]
    assert isinstance(analytics, list)
    assert analytics == ANALYTICS_LIST
    for a in analytics:
        assert "id" in a
        assert "name" in a
        assert "supportsTable" in a
        assert "supportsMap" in a
        assert "type" in a
        assert a["type"] in ("base", "selectable")


def test_list_analytics_includes_scores_table_analytic():
    """Scores is selectable in tabular mode."""
    response = client.get("/analytics")
    assert response.status_code == 200
    analytics = response.json()["analytics"]
    scores = next(a for a in analytics if a["id"] == "scores")
    assert scores == {
        "id": "scores",
        "name": "Scores",
        "supportsTable": True,
        "supportsMap": False,
        "type": "selectable",
    }


def test_scores_table_returns_scoreboard_columns_and_deltas():
    """Scores table mirrors the scoreboard columns except the generic Score column."""
    response = client.get(f"/analytics/scores/table?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    assert data["analyticId"] == "scores"
    assert data["columns"] == [
        "Race (player)",
        "Planets",
        "Starbases",
        "War Ships",
        "Freighters",
        "Military",
        "Priority Points",
    ]
    assert data["rows"][0] == [
        "koshling",
        "171 (-4)",
        "121 (-2)",
        "130 (+1)",
        "26",
        "2509092 (-53869)",
        "217 (+54)",
    ]


def test_scores_table_with_build_inference_adds_column_and_player_stubs():
    response = client.get(f"/analytics/scores/table?{SCOPE_QS}&includeBuildInference=true")
    assert response.status_code == 200
    data = response.json()
    assert data["includeBuildInference"] is True
    assert data["columns"][-1] == "Build inference"
    assert len(data["rows"][0]) == len(data["columns"]) - 1
    assert data["inferenceByRow"][0] == {"playerId": 8}


def test_scores_inference_returns_row_detail():
    response = client.get(f"/analytics/scores/inference?{SCOPE_QS}&playerId=8")
    assert response.status_code == 200
    inference = response.json()
    assert inference["displayStatus"] in {"success", "failure", "pending"}
    assert isinstance(inference["summary"], str)
    assert "status" in inference
    assert "diagnostics" in inference
    assert inference["playerId"] == 8
    assert inference["diagnostics"]["turn"] == 111
    assert "constraints" in inference["diagnostics"]
    assert "actionCatalog" in inference["diagnostics"]
    assert "solver" in inference["diagnostics"]


def test_scores_table_build_inference_disabled_matches_default_contract():
    default_response = client.get(f"/analytics/scores/table?{SCOPE_QS}")
    explicit_response = client.get(
        f"/analytics/scores/table?{SCOPE_QS}&includeBuildInference=false"
    )
    assert default_response.status_code == 200
    assert explicit_response.status_code == 200
    assert default_response.json() == explicit_response.json()
    assert "includeBuildInference" not in default_response.json()
    assert "inferenceByRow" not in default_response.json()


def test_base_map_returns_planets_and_no_edges():
    """GET /analytics/base-map/map returns planet nodes and no edges."""
    response = client.get(f"/analytics/base-map/map?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    assert data["analyticId"] == "base-map"
    nodes = data["nodes"]
    edges = data["edges"]
    assert len(nodes) > 0
    assert edges == []
    node_ids = {n["id"] for n in nodes}
    assert all(node_id.startswith("p") for node_id in node_ids)
    assert all(isinstance(n["x"], (int, float)) for n in nodes)
    assert all(isinstance(n["y"], (int, float)) for n in nodes)
    first = nodes[0]
    assert "planet" in first and isinstance(first["planet"], dict)
    assert "ownerName" in first
    assert "normalWellCells" in first
    assert len(first["normalWellCells"]) == 29


def test_get_analytic_map_unknown_id_returns_422():
    response = client.get(f"/analytics/unknown-analytic/map?{SCOPE_QS}")
    assert response.status_code == 422


def test_get_analytic_table_unknown_id_returns_422():
    response = client.get(f"/analytics/unknown-analytic/table?{SCOPE_QS}")
    assert response.status_code == 422


def test_get_analytic_table_unsupported_mode_returns_422():
    response = client.get(f"/analytics/base-map/table?{SCOPE_QS}")
    assert response.status_code == 422


def test_get_analytic_map_nodes_have_id_label_x_y():
    """Map response nodes must have id, label, x, y with numeric x and y."""
    response = client.get(f"/analytics/base-map/map?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    nodes = data["nodes"]
    assert len(nodes) >= 1, "map must return at least one node"
    for i, node in enumerate(nodes):
        assert "id" in node, f"node {i} missing id"
        assert "label" in node, f"node {i} missing label"
        assert "x" in node, f"node {i} missing x"
        assert "y" in node, f"node {i} missing y"
        x, y = node["x"], node["y"]
        assert isinstance(x, (int, float)), f"node {i} x must be numeric, got {type(x)}"
        assert isinstance(y, (int, float)), f"node {i} y must be numeric, got {type(y)}"
        assert not (isinstance(x, float) and math.isnan(x)), f"node {i} x must not be NaN"
        assert not (isinstance(y, float) and math.isnan(y)), f"node {i} y must not be NaN"


def test_connections_map_returns_routes_not_nodes():
    """Connections analytic returns route pairs for the SPA to bind to base-map planet ids."""
    qs = f"{SCOPE_QS}&warpSpeed=9&gravitonicMovement=false&flareMode=off&flareDepth=1"
    response = client.get(f"/analytics/connections/map?{qs}")
    assert response.status_code == 200
    data = response.json()
    assert data["analyticId"] == "connections"
    assert data["nodes"] == []
    assert data["edges"] == []
    assert "routes" in data
    assert isinstance(data["routes"], list)
    for row in data["routes"]:
        assert row["fromPlanetId"] < row["toPlanetId"]
        assert isinstance(row["viaFlare"], bool)


def test_connections_map_accepts_full_query_contract():
    """BFF accepts the same Connections query params as Core, including illustrative routes."""
    qs = (
        f"{SCOPE_QS}&warpSpeed=8&gravitonicMovement=true&flareMode=include&flareDepth=2"
        "&includeIllustrativeRoutes=true"
    )
    response = client.get(f"/analytics/connections/map?{qs}")
    assert response.status_code == 200
    data = response.json()
    assert data["analyticId"] == "connections"
    assert isinstance(data["routes"], list)


def test_stellar_cartography_map_returns_overlay_circles_and_wormhole_edges():
    """Stellar Cartography map returns overlay geometry and deduped wormhole edges."""
    storage = get_storage()
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        storage.put("games/628580/1/turns/111", json.load(f))
    response = client.get(f"/analytics/stellar-cartography/map?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    assert data["analyticId"] == "stellar-cartography"
    assert isinstance(data["overlayCircles"], list)
    assert len(data["overlayCircles"]) > 0
    layers = {circle["layer"] for circle in data["overlayCircles"]}
    assert "nebulae" in layers
    assert "ion-storms" in layers
    assert "star-clusters" in layers
    assert "black-holes" in layers
    bidirectional = [edge for edge in data["edges"] if edge.get("isBidirectional")]
    mono = [edge for edge in data["edges"] if not edge.get("isBidirectional")]
    assert len(bidirectional) == 1
    assert len(mono) == 1
    assert data["meta"]["wormholeEdges"] == 2


def test_list_analytics_includes_stellar_cartography_map_analytic():
    response = client.get("/analytics")
    assert response.status_code == 200
    analytics = response.json()["analytics"]
    stellar = next(a for a in analytics if a["id"] == "stellar-cartography")
    assert stellar["supportsTable"] is False
    assert stellar["supportsMap"] is True
    assert stellar["type"] == "selectable"


def test_list_analytics_includes_fleet_table_and_map_analytic():
    response = client.get("/analytics")
    assert response.status_code == 200
    analytics = response.json()["analytics"]
    fleet = next(a for a in analytics if a["id"] == "fleet")
    assert fleet == {
        "id": "fleet",
        "name": "Fleet",
        "supportsTable": True,
        "supportsMap": True,
        "type": "selectable",
    }


def test_fleet_table_returns_players_with_observed_records():
    response = client.get(f"/analytics/fleet/table?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    assert data["analyticId"] == "fleet"
    assert data["defaultActiveOnly"] is True
    assert isinstance(data.get("componentCatalog"), dict)
    players = data["players"]
    assert len(players) == 4
    assert players[0]["playerName"] == "koshling"
    koshling = next(player for player in players if player["playerId"] == 8)
    assert len(koshling["records"]) == 5
    first_record = koshling["records"][0]
    assert first_record["disposition"] == "active"
    assert "events" not in first_record
    assert "lastSeen" in first_record


def test_fleet_map_returns_scaffold_nodes():
    response = client.get(f"/analytics/fleet/map?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    assert data["analyticId"] == "fleet"
    players = data["players"]
    assert len(players) == 4
    for player in players:
        assert player["nodes"] == []
        assert player["overlayCircles"] == []
