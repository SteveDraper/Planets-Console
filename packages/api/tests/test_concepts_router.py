"""Tests for global concept routes (flare points)."""

import pytest
from api.config import ApiConfig, set_config
from api.storage import clear_backend_cache
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _setup_config():
    clear_backend_cache()
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    yield
    clear_backend_cache()


@pytest.fixture
def client():
    from api.app import app

    return TestClient(app, raise_server_exceptions=False)


class TestFlarePoints:
    def test_returns_200_with_expanded_table(self, client):
        resp = client.get(
            "/v1/concepts/flare-points",
            params={"warp_speed": 9, "movement_type": "regular"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["flare_points"]) == 60

    def test_gravitonic_movement_type(self, client):
        resp = client.get(
            "/v1/concepts/flare-points",
            params={"warp_speed": 9, "movement_type": "gravitonic"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["flare_points"]) == 132

    def test_warp_speed_out_of_range_422(self, client):
        resp = client.get(
            "/v1/concepts/flare-points",
            params={"warp_speed": 0, "movement_type": "regular"},
        )
        assert resp.status_code == 422

    def test_invalid_movement_type_422(self, client):
        resp = client.get(
            "/v1/concepts/flare-points",
            params={"warp_speed": 9, "movement_type": "nope"},
        )
        assert resp.status_code == 422
