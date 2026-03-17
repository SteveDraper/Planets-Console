"""Unit tests for store REST API: status codes, view=full|shallow, merge param, @ key rejection."""

from pathlib import Path

import pytest
from api.app import app
from api.config import ApiConfig, set_config
from api.storage import clear_backend_cache
from fastapi.testclient import TestClient

# Asset used by router tests: inject via config (see client fixture).
TEST_ASSET_PATH = Path(__file__).resolve().parent / "fixtures" / "store_router_initial.json"


@pytest.fixture
def client():
    """Test client with config pointing at test asset; backend cache cleared per test."""
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=str(TEST_ASSET_PATH),
            include_dummy_data=False,
        )
    )
    clear_backend_cache()
    try:
        yield TestClient(app)
    finally:
        clear_backend_cache()


def test_get_full_returns_node(client):
    response = client.get("/v1/store/planets/sol/earth")
    assert response.status_code == 200
    assert response.json() == {"name": "Earth"}


def test_get_shallow_returns_metadata_and_children(client):
    response = client.get("/v1/store/planets/sol?view=shallow")
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == "planets/sol"
    assert data["node_type"] == "object"
    assert set(data["children"]) == {"earth", "arr"}
    assert data["count"] == 2


def test_get_invalid_view_returns_422(client):
    response = client.get("/v1/store/game?view=invalid")
    assert response.status_code == 422


def test_get_missing_returns_404(client):
    response = client.get("/v1/store/missing/path")
    assert response.status_code == 404


def test_put_create_returns_201(client):
    response = client.put("/v1/store/new/resource", json={"created": True})
    assert response.status_code == 201
    assert client.get("/v1/store/new/resource").json() == {"created": True}


def test_put_existing_returns_409(client):
    response = client.put("/v1/store/game", json={"overwrite": True})
    assert response.status_code == 409


def test_put_reserved_at_key_returns_422(client):
    response = client.put("/v1/store/x", json={"@reserved": 1})
    assert response.status_code == 422


def test_post_update_merge_returns_200(client):
    response = client.post("/v1/store/planets/sol/earth", json={"moons": ["Luna"]})
    assert response.status_code == 200
    assert response.json()["moons"] == ["Luna"]


def test_post_merge_append_returns_200(client):
    response = client.post(
        "/v1/store/planets/sol/arr",
        json=4,
        params={"merge": "append"},
    )
    assert response.status_code == 200
    assert response.json() == [1, 2, 3, 4]


def test_post_invalid_merge_param_returns_422(client):
    response = client.post(
        "/v1/store/planets/sol/arr",
        json=4,
        params={"merge": "invalid"},
    )
    assert response.status_code == 422


def test_delete_returns_204(client):
    client.put("/v1/store/todelete", json={"x": 1})
    response = client.delete("/v1/store/todelete")
    assert response.status_code == 204
    assert client.get("/v1/store/todelete").status_code == 404


def test_delete_missing_returns_404(client):
    response = client.delete("/v1/store/nonexistent/path")
    assert response.status_code == 404
