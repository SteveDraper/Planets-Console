"""Freeze stream narrowing must not drop the AC, and empty allowlist must narrow to ().

Client completion semantics (stay pending, do not mark failed) are covered on the
frontend via computeFreezeStreamHold. This test locks the BFF narrowing contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.services.compute_diagnostics_service import (
    get_compute_diagnostics_freeze_status,
    get_compute_diagnostics_stream_allowlist,
    reset_compute_diagnostics_for_tests,
    set_compute_diagnostics_allowlist,
    set_compute_diagnostics_freeze_armed,
)
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
            compute_diagnostics=True,
        )
    )
    yield
    clear_core_client_cache()
    clear_backend_cache()
    reset_compute_diagnostics_for_tests()


def test_fleet_table_stream_narrows_to_empty_when_freeze_allowlist_empty():
    """Freeze + empty allowlist narrows subscriptions to no players (AC)."""
    set_compute_diagnostics_freeze_armed(
        game_id=628580,
        perspective=1,
        turn=8,
        freeze_armed=True,
    )
    freeze_armed, allowlisted = get_compute_diagnostics_freeze_status(
        game_id=628580,
        perspective=1,
        turn=8,
    )
    assert freeze_armed is True
    assert allowlisted == frozenset()

    captured: list[tuple[int, ...]] = []

    def _iter_fleet_table_stream(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
    ):
        del game_id, perspective, turn_number
        captured.append(player_ids)
        yield from ()

    mock_core = MagicMock()
    mock_core.iter_fleet_table_stream = _iter_fleet_table_stream

    with patch("bff.routers.fleet_table_stream.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/fleet/table-stream?gameId=628580&perspective=1&turn=8&playerIds=3,7,11"
        )

    assert response.status_code == 200
    assert captured == [()]


def test_fleet_table_stream_narrows_to_allowlisted_players():
    set_compute_diagnostics_freeze_armed(
        game_id=628580,
        perspective=1,
        turn=8,
        freeze_armed=True,
    )
    set_compute_diagnostics_allowlist(
        game_id=628580,
        perspective=1,
        turn=8,
        player_ids=frozenset({7, 11}),
    )

    captured: list[tuple[int, ...]] = []

    def _iter_fleet_table_stream(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
    ):
        del game_id, perspective, turn_number
        captured.append(player_ids)
        yield from ()

    mock_core = MagicMock()
    mock_core.iter_fleet_table_stream = _iter_fleet_table_stream

    with patch("bff.routers.fleet_table_stream.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/fleet/table-stream?gameId=628580&perspective=1&turn=8&playerIds=3,7,11"
        )

    assert response.status_code == 200
    assert captured == [(7, 11)]


def test_fleet_table_stream_disarms_previous_game_freeze_on_context_change():
    """Opening a stream for game B must disarm freeze left armed on game A."""
    set_compute_diagnostics_freeze_armed(
        game_id=628580,
        perspective=1,
        turn=8,
        freeze_armed=True,
    )
    assert (
        get_compute_diagnostics_stream_allowlist(
            game_id=628580,
            perspective=1,
            turn=8,
        )
        == frozenset()
    )

    captured: list[tuple[int, ...]] = []

    def _iter_fleet_table_stream(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
    ):
        del game_id, perspective, turn_number
        captured.append(player_ids)
        yield from ()

    mock_core = MagicMock()
    mock_core.iter_fleet_table_stream = _iter_fleet_table_stream

    with patch("bff.routers.fleet_table_stream.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/fleet/table-stream?gameId=999001&perspective=1&turn=8&playerIds=3,7"
        )

    assert response.status_code == 200
    assert captured == [(3, 7)]
    # Game A freeze must be cleared; stream narrowing returns None when unarmed.
    assert (
        get_compute_diagnostics_stream_allowlist(
            game_id=628580,
            perspective=1,
            turn=8,
        )
        is None
    )
