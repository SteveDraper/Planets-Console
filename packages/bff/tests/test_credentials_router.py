"""BFF credentials router HTTP contracts."""

from unittest.mock import patch

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.services.credential_service import CredentialService
from api.storage import clear_backend_cache, get_storage
from bff.app import app
from bff.config import BffConfig
from bff.config import set_config as set_bff_config
from bff.core_client import clear_core_client_cache
from fastapi.testclient import TestClient

client = TestClient(app)

_MACHINE = "bff-credentials-test-machine"


@pytest.fixture(autouse=True)
def _reset():
    clear_backend_cache()
    clear_core_client_cache()
    set_bff_config(BffConfig())
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
            credentials_obfuscation_secret=None,
        )
    )
    yield
    clear_core_client_cache()
    clear_backend_cache()


def _store_key(username: str, api_key: str = "cached-key") -> None:
    CredentialService(
        get_storage(),
        machine_id_reader=lambda: _MACHINE,
        obfuscation_secret=None,
    ).store_api_key(username, api_key)


def test_probe_present_false_by_default():
    response = client.get("/credentials/probe", params={"username": "alice"})
    assert response.status_code == 200
    assert response.json() == {"present": False}


def test_probe_present_true_when_key_stored():
    _store_key("alice")
    with patch(
        "api.services.credential_service.read_os_machine_id",
        return_value=_MACHINE,
    ):
        clear_core_client_cache()
        response = client.get("/credentials/probe", params={"username": "alice"})
    assert response.status_code == 200
    assert response.json() == {"present": True}


@patch("bff.core_client.PlanetsNuClient")
def test_exchange_success(mock_pc_class):
    mock_instance = mock_pc_class.from_config.return_value
    mock_instance.login.return_value = "exchanged-key"
    with patch(
        "api.services.credential_service.read_os_machine_id",
        return_value=_MACHINE,
    ):
        clear_core_client_cache()
        response = client.post(
            "/credentials/exchange",
            json={"username": "alice", "password": "secret"},
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_instance.login.assert_called_once_with("alice", "secret")
    with patch(
        "api.services.credential_service.read_os_machine_id",
        return_value=_MACHINE,
    ):
        assert (
            client.get("/credentials/probe", params={"username": "alice"}).json()["present"] is True
        )


@patch("bff.core_client.PlanetsNuClient")
def test_exchange_maps_validation_error(mock_pc_class):
    from api.errors import ValidationError

    mock_instance = mock_pc_class.from_config.return_value
    mock_instance.login.side_effect = ValidationError("Invalid username or password.")
    with patch(
        "api.services.credential_service.read_os_machine_id",
        return_value=_MACHINE,
    ):
        clear_core_client_cache()
        response = client.post(
            "/credentials/exchange",
            json={"username": "alice", "password": "secret"},
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid username or password."


def test_drop_returns_204():
    _store_key("alice")
    with patch(
        "api.services.credential_service.read_os_machine_id",
        return_value=_MACHINE,
    ):
        clear_core_client_cache()
        response = client.delete("/credentials/alice")
        assert response.status_code == 204
        assert (
            client.get("/credentials/probe", params={"username": "alice"}).json()["present"]
            is False
        )


def test_probe_requires_username():
    response = client.get("/credentials/probe")
    assert response.status_code == 422
