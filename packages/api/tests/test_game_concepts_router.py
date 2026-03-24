"""Tests for turn-scoped game concept routes (warp wells)."""

import json
from pathlib import Path

import pytest
from api.config import ApiConfig, set_config
from api.storage import clear_backend_cache, get_storage
from fastapi.testclient import TestClient

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _setup_storage():
    clear_backend_cache()
    set_config(
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


@pytest.fixture
def client():
    from api.app import app

    return TestClient(app, raise_server_exceptions=False)


class TestWarpWellCoordinateInWell:
    def test_returns_200(self, client):
        resp = client.post(
            "/v1/games/628580/1/turns/111/concepts/warp-wells/coordinate-in-well",
            json={
                "planet_id": 1,
                "map_x": 2078,
                "map_y": 1149,
                "well_type": "normal",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"inside": True}

    def test_hyperjump_excludes_distance_three(self, client):
        resp = client.post(
            "/v1/games/628580/1/turns/111/concepts/warp-wells/coordinate-in-well",
            json={
                "planet_id": 1,
                "map_x": 2081,
                "map_y": 1149,
                "well_type": "hyperjump",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"inside": False}

    def test_404_unknown_planet(self, client):
        resp = client.post(
            "/v1/games/628580/1/turns/111/concepts/warp-wells/coordinate-in-well",
            json={
                "planet_id": 999999999,
                "map_x": 0,
                "map_y": 0,
                "well_type": "normal",
            },
        )
        assert resp.status_code == 404


class TestWarpWellCells:
    def test_returns_200_with_cells(self, client):
        resp = client.get(
            "/v1/games/628580/1/turns/111/concepts/warp-wells/cells",
            params={"planet_id": 1, "well_type": "normal"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "cells" in data
        assert isinstance(data["cells"], list)
        assert len(data["cells"]) > 0
        assert {"x": 2078, "y": 1149} in data["cells"]

    def test_404_unknown_planet(self, client):
        resp = client.get(
            "/v1/games/628580/1/turns/111/concepts/warp-wells/cells",
            params={"planet_id": 999999999, "well_type": "normal"},
        )
        assert resp.status_code == 404
