"""Tests for the BFF CoreClient facade."""

from unittest.mock import MagicMock

import pytest
from api.errors import NotFoundError, ValidationError
from api.models.game_info_operations import GameInfoUpdateOperation
from api.services.game_service import GameService, clear_sector_title_cache
from api.transport.concept_warp_well import CoordinateInWarpWellRequest, WarpWellTypeParam
from api.transport.game_info_update import GameInfoUpdateRequest
from api.transport.turn_ensure import TurnEnsureRequest
from bff.core_client import CoreClient, clear_core_client_cache, get_core_client
from fastapi import HTTPException


def _core_client(**overrides: object) -> CoreClient:
    defaults: dict[str, object] = {
        "game_service": MagicMock(spec=GameService),
        "turn_load_service": MagicMock(),
        "load_all_turns_service": MagicMock(),
        "turn_concept_service": MagicMock(),
        "turn_analytic_service": MagicMock(),
        "credential_service": MagicMock(),
    }
    defaults.update(overrides)
    return CoreClient(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear_sector_cache():
    clear_sector_title_cache()
    clear_core_client_cache()
    yield
    clear_sector_title_cache()
    clear_core_client_cache()


def test_get_core_client_returns_process_singleton():
    first = get_core_client()
    second = get_core_client()
    assert first is second


def test_get_turn_analytics_maps_core_errors_to_http():
    analytics = MagicMock()
    analytics.get_turn_analytics.side_effect = ValidationError("bad scope")
    client = _core_client(turn_analytic_service=analytics)

    with pytest.raises(HTTPException) as exc:
        client.get_turn_analytics(1, 1, 1, "connections")

    assert exc.value.status_code == 422
    assert exc.value.detail == "bad scope"


def test_list_stored_games_delegates_to_game_service():
    games = MagicMock()
    games.list_stored_games.return_value = {"games": []}
    client = _core_client(game_service=games)

    assert client.list_stored_games() == {"games": []}
    games.list_stored_games.assert_called_once()


def test_list_stored_games_maps_game_service_errors_to_http():
    games = MagicMock()
    games.list_stored_games.side_effect = ValidationError("bad games path")
    client = _core_client(game_service=games)

    with pytest.raises(HTTPException) as exc:
        client.list_stored_games()

    assert exc.value.status_code == 422
    assert exc.value.detail == "bad games path"


def test_warp_well_coordinate_in_well_delegates_to_shared_handler():
    concepts = MagicMock()
    concepts.warp_well_coordinate_in_well.return_value = True
    client = _core_client(turn_concept_service=concepts)
    body = CoordinateInWarpWellRequest(
        planet_id=1,
        map_x=10.0,
        map_y=20.0,
        well_type=WarpWellTypeParam.NORMAL,
    )

    result = client.warp_well_coordinate_in_well(628580, 1, 111, body)

    assert result.inside is True
    concepts.warp_well_coordinate_in_well.assert_called_once()


def test_refresh_game_info_delegates_to_game_service():
    games = MagicMock()
    info = MagicMock()
    games.update_game_info.return_value = info
    client = _core_client(
        game_service=games,
        planets_client_factory=lambda: MagicMock(),
    )
    body = GameInfoUpdateRequest(
        operation=GameInfoUpdateOperation.REFRESH,
        params={"username": "player1"},
    )

    result = client.refresh_game_info(628580, body)

    assert result is info
    games.update_game_info.assert_called_once()


def test_ensure_turn_returns_stored_turn_without_planets_client():
    turns = MagicMock()
    turn = MagicMock()
    turns.get_turn_info.return_value = turn
    factory = MagicMock()
    client = _core_client(
        turn_load_service=turns,
        planets_client_factory=factory,
    )
    body = TurnEnsureRequest(turn=111, perspective=1, username="player1")

    result = client.ensure_turn(628580, body)

    assert result is turn
    turns.get_turn_info.assert_called_once_with(628580, 1, 111)
    turns.ensure_turn_loaded.assert_not_called()
    factory.assert_not_called()


def test_ensure_turn_delegates_with_refresh_params():
    turns = MagicMock()
    turn = MagicMock()
    turns.get_turn_info.side_effect = NotFoundError("missing")
    turns.ensure_turn_loaded.return_value = turn
    planets = MagicMock()
    client = _core_client(
        turn_load_service=turns,
        planets_client_factory=lambda: planets,
    )
    body = TurnEnsureRequest(turn=111, perspective=1, username="player1")

    result = client.ensure_turn(628580, body)

    assert result is turn
    turns.get_turn_info.assert_called_once_with(628580, 1, 111)
    turns.ensure_turn_loaded.assert_called_once()
    assert turns.ensure_turn_loaded.call_args[0][4] is planets
