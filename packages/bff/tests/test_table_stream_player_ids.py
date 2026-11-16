"""Table streams subscribe every requested player, whatever compute diagnostics freeze says.

Freeze holds dispatch in Core; it never narrows which rows a stream opens. With
freeze armed and an empty focus allowlist, the BFF still forwards every player.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.services.compute_diagnostics_service import (
    reset_compute_diagnostics_for_tests,
    set_compute_diagnostics_freeze_armed,
)
from api.storage_factory import clear_backend_cache
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


def _arm_freeze_with_an_empty_allowlist() -> None:
    set_compute_diagnostics_freeze_armed(
        game_id=628580,
        perspective=1,
        turn=8,
        freeze_armed=True,
    )


def _capturing_stream(captured: list[tuple[int, ...]]):
    def _iter_table_stream(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
        *,
        username: str = "",
    ):
        del game_id, perspective, turn_number, username
        captured.append(player_ids)
        yield from ()

    return _iter_table_stream


def test_fleet_table_stream_forwards_every_player_while_freeze_is_armed():
    _arm_freeze_with_an_empty_allowlist()
    captured: list[tuple[int, ...]] = []
    mock_core = MagicMock()
    mock_core.iter_fleet_table_stream = _capturing_stream(captured)

    with patch("bff.routers.fleet_table_stream.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/fleet/table-stream?gameId=628580&perspective=1&turn=8&playerIds=3,7,11"
        )

    assert response.status_code == 200
    assert captured == [(3, 7, 11)]


def test_scores_inference_table_stream_forwards_every_player_while_freeze_is_armed():
    _arm_freeze_with_an_empty_allowlist()
    captured: list[tuple[int, ...]] = []
    mock_core = MagicMock()
    mock_core.iter_scores_table_inference_stream = _capturing_stream(captured)

    with patch("bff.routers.scores_inference.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/scores/inference/table-stream"
            "?gameId=628580&perspective=1&turn=8&playerIds=3,7,11"
        )

    assert response.status_code == 200
    assert captured == [(3, 7, 11)]


def test_fleet_table_stream_forwards_username_to_core():
    captured: list[str] = []

    def _iter_fleet_table_stream(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
        *,
        username: str = "",
    ):
        del game_id, perspective, turn_number, player_ids
        captured.append(username)
        yield from ()

    mock_core = MagicMock()
    mock_core.iter_fleet_table_stream = _iter_fleet_table_stream

    with patch("bff.routers.fleet_table_stream.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/fleet/table-stream"
            "?gameId=628580&perspective=1&turn=8&playerIds=3&username=captain"
        )

    assert response.status_code == 200
    assert captured == ["captain"]


def test_scores_inference_table_stream_forwards_username_to_core():
    captured: list[str] = []

    def _iter_scores_table_inference_stream(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
        *,
        username: str = "",
    ):
        del game_id, perspective, turn_number, player_ids
        captured.append(username)
        yield from ()

    mock_core = MagicMock()
    mock_core.iter_scores_table_inference_stream = _iter_scores_table_inference_stream

    with patch("bff.routers.scores_inference.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/scores/inference/table-stream"
            "?gameId=628580&perspective=1&turn=8&playerIds=3&username=captain"
        )

    assert response.status_code == 200
    assert captured == ["captain"]
