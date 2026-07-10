"""BFF compute diagnostics routes."""

from __future__ import annotations

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.services.compute_diagnostics_service import reset_compute_diagnostics_for_tests
from api.storage import clear_backend_cache
from bff.app import app
from bff.config import BffConfig
from bff.config import set_config as set_bff_config
from bff.core_client import clear_core_client_cache
from bff.diagnostics_buffer import get_diagnostics_buffer
from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset():
    clear_backend_cache()
    clear_core_client_cache()
    reset_compute_diagnostics_for_tests()
    set_bff_config(BffConfig(diagnostics_buffer_size=10))
    get_diagnostics_buffer().clear()
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
            compute_diagnostics=False,
        )
    )
    yield
    clear_core_client_cache()
    clear_backend_cache()
    reset_compute_diagnostics_for_tests()


def test_compute_diagnostics_disabled_returns_404():
    response = client.get("/diagnostics/compute/snapshot?gameId=1&perspective=1&turn=8")
    assert response.status_code == 404
    freeze_status = client.get("/diagnostics/compute/freeze-status?gameId=1&perspective=1&turn=8")
    assert freeze_status.status_code == 404


def test_compute_diagnostics_freeze_status_without_heavy_snapshot():
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
            compute_diagnostics=True,
        )
    )
    client.put(
        "/diagnostics/compute/freeze",
        json={"gameId": 628580, "perspective": 1, "turn": 8, "freezeArmed": True},
    )
    client.put(
        "/diagnostics/compute/allowlist",
        json={"gameId": 628580, "perspective": 1, "turn": 8, "playerIds": [3, 7]},
    )

    status = client.get("/diagnostics/compute/freeze-status?gameId=628580&perspective=1&turn=8")
    assert status.status_code == 200
    body = status.json()
    assert body == {
        "shell": {"gameId": 628580, "perspective": 1, "turn": 8},
        "freezeArmed": True,
        "allowlistedPlayerIds": [3, 7],
    }
    assert "poolQueue" not in body
    assert "dagNodes" not in body


def test_compute_diagnostics_enabled_snapshot_and_freeze():
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
            compute_diagnostics=True,
        )
    )
    enabled = client.get("/diagnostics/compute/enabled")
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True}

    snapshot = client.get("/diagnostics/compute/snapshot?gameId=628580&perspective=1&turn=8")
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body["shell"] == {"gameId": 628580, "perspective": 1, "turn": 8}
    assert body["freezeArmed"] is False
    assert "clientStreams" not in body
    assert "poolQueue" in body
    assert "inFlight" in body
    assert "dagNodes" in body
    assert "readyQueue" in body
    assert "completionHistory" in body
    assert "serverStreams" in body

    missing_client_streams = client.put(
        "/diagnostics/compute/client-streams?gameId=628580&perspective=1&turn=8",
        json=[],
    )
    assert missing_client_streams.status_code == 404

    freeze = client.put(
        "/diagnostics/compute/freeze",
        json={"gameId": 628580, "perspective": 1, "turn": 8, "freezeArmed": True},
    )
    assert freeze.status_code == 200
    assert freeze.json()["freezeArmed"] is True

    allowlist = client.put(
        "/diagnostics/compute/allowlist",
        json={"gameId": 628580, "perspective": 1, "turn": 8, "playerIds": [3, 4]},
    )
    assert allowlist.status_code == 200
    assert allowlist.json()["allowlistedPlayerIds"] == [3, 4]

    single_step = client.post(
        "/diagnostics/compute/single-step",
        json={"gameId": 628580, "perspective": 1, "turn": 8},
    )
    assert single_step.status_code == 200

    bootstrap = client.get("/shell/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["computeDiagnosticsEnabled"] is True


def test_sticky_freeze_across_turn_and_perspective_resets_allowlist():
    """Freeze stays armed within a game; allowlist clears on shell context change."""
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
            compute_diagnostics=True,
        )
    )
    freeze = client.put(
        "/diagnostics/compute/freeze",
        json={"gameId": 628580, "perspective": 1, "turn": 8, "freezeArmed": True},
    )
    assert freeze.status_code == 200
    assert freeze.json()["freezeArmed"] is True

    allowlist = client.put(
        "/diagnostics/compute/allowlist",
        json={"gameId": 628580, "perspective": 1, "turn": 8, "playerIds": [3, 7]},
    )
    assert allowlist.status_code == 200
    assert allowlist.json()["allowlistedPlayerIds"] == [3, 7]

    turn_change = client.get("/diagnostics/compute/snapshot?gameId=628580&perspective=1&turn=9")
    assert turn_change.status_code == 200
    turn_body = turn_change.json()
    assert turn_body["freezeArmed"] is True
    assert turn_body["allowlistedPlayerIds"] == []

    # Re-apply allowlist on the new turn, then change perspective.
    client.put(
        "/diagnostics/compute/allowlist",
        json={"gameId": 628580, "perspective": 1, "turn": 9, "playerIds": [11]},
    )
    perspective_change = client.get(
        "/diagnostics/compute/snapshot?gameId=628580&perspective=2&turn=9"
    )
    assert perspective_change.status_code == 200
    perspective_body = perspective_change.json()
    assert perspective_body["freezeArmed"] is True
    assert perspective_body["allowlistedPlayerIds"] == []

    game_change = client.get("/diagnostics/compute/snapshot?gameId=999001&perspective=2&turn=9")
    assert game_change.status_code == 200
    assert game_change.json()["freezeArmed"] is False

    # Prior game is disarmed after leaving it.
    prior_game = client.get("/diagnostics/compute/snapshot?gameId=628580&perspective=2&turn=9")
    assert prior_game.status_code == 200
    assert prior_game.json()["freezeArmed"] is False
