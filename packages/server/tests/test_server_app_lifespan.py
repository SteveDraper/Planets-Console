"""Combined server app: mounted Core API lifespan is not run by Starlette; seed here."""

from __future__ import annotations

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.storage import clear_backend_cache, get_storage
from fastapi.testclient import TestClient


@pytest.fixture
def _api_config_and_storage():
    clear_backend_cache()
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=True,
        )
    )
    yield
    clear_backend_cache()


def test_root_app_lifespan_seeds_when_include_dummy_data(_api_config_and_storage):
    from server.app import app

    with TestClient(app):
        raw = get_storage().get("games/628580/info")
    assert isinstance(raw, dict)
    assert raw.get("game", {}).get("id") == 628580


def test_diagnostics_recent_alias_matches_bff_mount(_api_config_and_storage):
    """Root app exposes MRU at both /bff/diagnostics/recent and /diagnostics/recent."""
    from server.app import app

    c = TestClient(app)
    r1 = c.get("/bff/diagnostics/recent")
    r2 = c.get("/diagnostics/recent")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json() == {"items": []}
