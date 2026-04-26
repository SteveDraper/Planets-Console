"""BFF shell bootstrap routes."""

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
    set_bff_config(BffConfig())
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


def test_shell_bootstrap_null_when_unconfigured():
    response = client.get("/shell/bootstrap")
    assert response.status_code == 200
    assert response.json() == {"showInitialGame": None}


def test_shell_bootstrap_returns_trimmed_game_id():
    set_bff_config(BffConfig(show_initial_game="  628580  "))
    response = client.get("/shell/bootstrap")
    assert response.status_code == 200
    assert response.json() == {"showInitialGame": "628580"}
