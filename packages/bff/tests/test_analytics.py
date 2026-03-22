"""Unit tests for BFF analytics routes. Verify response shape and map node coordinates."""

import json
import math
from pathlib import Path

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.storage import clear_backend_cache, get_storage
from bff.app import app
from fastapi.testclient import TestClient

client = TestClient(app)

SCOPE_QS = "gameId=628580&turn=111&perspective=1"

REPO_PACKAGES_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = REPO_PACKAGES_DIR / "api" / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _setup_storage_for_core_calls():
    """Seed Core storage so BFF can call Core via ASGI transport."""
    clear_backend_cache()
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
        storage.put("games/628580/1/turns/111", json.load(f))
    yield
    clear_backend_cache()


def test_list_analytics_returns_analytics_list():
    """GET /analytics returns list of analytics with expected fields."""
    response = client.get("/analytics")
    assert response.status_code == 200
    data = response.json()
    assert "analytics" in data
    analytics = data["analytics"]
    assert isinstance(analytics, list)
    assert len(analytics) >= 1
    for a in analytics:
        assert "id" in a
        assert "name" in a
        assert "supportsTable" in a
        assert "supportsMap" in a
        assert "type" in a
        assert a["type"] in ("base", "selectable")


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


def test_get_analytic_map_returns_expected_structure():
    """GET /analytics/{id}/map returns analyticId, nodes, edges."""
    response = client.get(f"/analytics/placeholder-2/map?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    assert "analyticId" in data
    assert data["analyticId"] == "placeholder-2"
    assert "nodes" in data
    assert "edges" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)


def test_get_analytic_map_nodes_have_id_label_x_y():
    """Map response nodes must have id, label, x, y with numeric x and y."""
    response = client.get(f"/analytics/placeholder-2/map?{SCOPE_QS}")
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


def test_get_analytic_map_placeholder_has_four_nodes_with_distinct_coordinates():
    """Placeholder map returns 4 nodes with distinct (x,y) in a 200x200 square."""
    response = client.get(f"/analytics/placeholder-2/map?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    nodes = data["nodes"]
    assert len(nodes) == 4, "placeholder map must return exactly 4 nodes"
    coords = [(n["x"], n["y"]) for n in nodes]
    expected = {(0, 0), (200, 0), (200, 200), (0, 200)}
    assert set(coords) == expected, f"expected nodes at {expected}, got {coords}"


def test_get_analytic_map_edges_reference_node_ids():
    """Map edges source/target must match node ids."""
    response = client.get(f"/analytics/placeholder-2/map?{SCOPE_QS}")
    assert response.status_code == 200
    data = response.json()
    node_ids = {n["id"] for n in data["nodes"]}
    for edge in data["edges"]:
        assert "source" in edge and "target" in edge
        assert edge["source"] in node_ids, f"edge source {edge['source']} not in node ids"
        assert edge["target"] in node_ids, f"edge target {edge['target']} not in node ids"
