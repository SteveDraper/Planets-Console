"""BFF diagnostics buffer and recent endpoint."""

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.storage import clear_backend_cache
from bff.app import app
from bff.config import BffConfig
from bff.config import set_config as set_bff_config
from bff.diagnostics_buffer import get_diagnostics_buffer
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    clear_backend_cache()
    set_bff_config(BffConfig(diagnostics_buffer_size=10))
    get_diagnostics_buffer().clear()
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    yield
    clear_backend_cache()


def test_diagnostics_recent_empty_by_default():
    r = client.get("/diagnostics/recent")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_diagnostics_recent_under_bff_prefix_when_bff_is_root_app():
    """Browser + Vite proxy use ``/bff/diagnostics/recent`` even when BFF runs alone."""
    r = client.get("/bff/diagnostics/recent")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_diagnostics_captured_after_bootstrap_with_flag():
    r0 = client.get("/shell/bootstrap?includeDiagnostics=true")
    assert r0.status_code == 200
    j = r0.json()
    assert "diagnostics" in j
    assert j["diagnostics"]["name"] == "GET /shell/bootstrap"
    r1 = client.get("/diagnostics/recent")
    assert r1.status_code == 200
    items = r1.json()["items"]
    assert len(items) == 1
    assert items[0]["summary"] == "GET /shell/bootstrap"
    assert items[0]["diagnostics"] == j["diagnostics"]
