"""Tests for the BFF CoreClient facade."""

from unittest.mock import MagicMock

import pytest
from api.errors import NotFoundError, ValidationError
from api.models.game_info_operations import GameInfoUpdateOperation
from api.transport.concept_warp_well import CoordinateInWarpWellRequest, WarpWellTypeParam
from api.transport.game_info_update import GameInfoUpdateRequest
from api.transport.turn_ensure import TurnEnsureRequest
from bff.core_client import CoreClient, clear_sector_title_cache
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def _clear_sector_cache():
    clear_sector_title_cache()
    yield
    clear_sector_title_cache()


def test_get_turn_analytics_maps_core_errors_to_http():
    analytics = MagicMock()
    analytics.get_turn_analytics.side_effect = ValidationError("bad scope")
    client = CoreClient(turn_analytic_service=analytics, store_service=MagicMock())

    with pytest.raises(HTTPException) as exc:
        client.get_turn_analytics(1, 1, 1, "connections")

    assert exc.value.status_code == 422
    assert exc.value.detail == "bad scope"


def test_list_stored_games_returns_empty_when_games_path_missing():
    store = MagicMock()
    store.read_shallow.side_effect = NotFoundError("missing")
    client = CoreClient(store_service=store)

    assert client.list_stored_games() == {"games": []}


def test_warp_well_coordinate_in_well_delegates_to_shared_handler():
    concepts = MagicMock()
    concepts.warp_well_coordinate_in_well.return_value = True
    client = CoreClient(turn_concept_service=concepts, store_service=MagicMock())
    body = CoordinateInWarpWellRequest(
        planet_id=1,
        map_x=10.0,
        map_y=20.0,
        well_type=WarpWellTypeParam.NORMAL,
    )

    result = client.warp_well_coordinate_in_well(628580, 1, 111, body)

    assert result.inside is True
    concepts.warp_well_coordinate_in_well.assert_called_once()


def test_refresh_game_info_updates_sector_title_cache():
    games = MagicMock()
    info = MagicMock()
    info.game.name = "Cached Sector"
    info.settings.name = None
    games.update_game_info.return_value = info
    client = CoreClient(
        game_service=games,
        store_service=MagicMock(),
        planets_client_factory=lambda: MagicMock(),
    )
    body = GameInfoUpdateRequest(
        operation=GameInfoUpdateOperation.REFRESH,
        params={"username": "player1"},
    )

    client.refresh_game_info(628580, body)

    assert client._resolved_sector_title_for_listed_game("628580") == "Cached Sector"


def test_ensure_turn_delegates_with_refresh_params():
    turns = MagicMock()
    turn = MagicMock()
    turns.ensure_turn_loaded.return_value = turn
    planets = MagicMock()
    client = CoreClient(
        turn_load_service=turns,
        store_service=MagicMock(),
        planets_client_factory=lambda: planets,
    )
    body = TurnEnsureRequest(turn=111, perspective=1, username="player1")

    result = client.ensure_turn(628580, body)

    assert result is turn
    turns.ensure_turn_loaded.assert_called_once()
    assert turns.ensure_turn_loaded.call_args[0][4] is planets
