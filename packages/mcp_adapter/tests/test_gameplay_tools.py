"""In-process MCP named gameplay tools: wrap mapping and shell-context gates."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from api.concepts.disk_proximity import DiskProximityHit
from api.concepts.flare_points import FlareMovementKind
from api.concepts.planet_connections.connection_engine import ConnectionRoutesOutcome
from api.concepts.warp_well import WarpWellKind
from api.models.flare_point import FlarePoint
from api.models.game import GameInfo
from api.services.game_service import GameService
from api.services.turn_load_service import TurnLoadService
from api.transport.connections_options import FlareConnectionMode
from mcp_adapter.gameplay import HYPERJUMP_NOT_JUMPING_REASON
from mcp_adapter.server import (
    DISK_PROXIMITY_TOOL,
    DISTANCE_LY_TOOL,
    FLARE_ENDPOINTS_TOOL,
    HYPERJUMP_LANDING_TOOL,
    POINT_IN_WARP_WELL_TOOL,
    REACHABLE_PLANETS_TOOL,
    SAMPLE_STELLAR_CARTOGRAPHY_TOOL,
    STELLAR_CARTOGRAPHY_SUMMARY_TOOL,
    WARP_WELL_CELLS_TOOL,
)
from mcp_adapter.shell_context import NEEDS_ENSURE_RESULT

from tests.mcp_test_support import build_test_mcp, call_tool, resolve_as, stored_turn_mcp

_GAME_ID = 628580
_TURN = 111
_PERSPECTIVE = 2
_SHELL = {"game_id": _GAME_ID, "turn": _TURN, "perspective": _PERSPECTIVE}


def test_point_in_warp_well_wraps_coordinate_in_warp_well(running_game_info: GameInfo):
    planet = MagicMock()
    planet.id = 17
    turn = MagicMock()
    turn.planets = [planet]
    mcp, _, turns = stored_turn_mcp(running_game_info, turn)

    with patch("mcp_adapter.gameplay.coordinate_in_warp_well", return_value=True) as concept:
        result = call_tool(
            mcp,
            POINT_IN_WARP_WELL_TOOL,
            {**_SHELL, "planet_id": 17, "x": 101.5, "y": 202.0, "well_kind": "hyperjump"},
        )

    assert result.is_error is False
    assert result.structured_content == {"inside": True}
    concept.assert_called_once_with(planet, 101.5, 202.0, WarpWellKind.HYPERJUMP)
    turns.get_turn_info.assert_called_once_with(_GAME_ID, _PERSPECTIVE, _TURN)


def test_warp_well_cells_maps_cell_indices(running_game_info: GameInfo):
    planet = MagicMock()
    planet.id = 3
    turn = MagicMock()
    turn.planets = [planet]
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    with patch(
        "mcp_adapter.gameplay.map_cell_indices_in_warp_well",
        return_value=[(10, 11), (12, 13)],
    ) as concept:
        result = call_tool(
            mcp,
            WARP_WELL_CELLS_TOOL,
            {**_SHELL, "planet_id": 3, "well_kind": "normal"},
        )

    assert result.is_error is False
    assert result.structured_content == {"cells": [{"x": 10, "y": 11}, {"x": 12, "y": 13}]}
    concept.assert_called_once_with(planet, WarpWellKind.NORMAL)


def test_flare_endpoints_adds_origin_to_offsets():
    mcp = build_test_mcp()
    point = FlarePoint(
        waypoint_offset=(10, 0),
        arrival_offset=(9, 1),
        direct_aim_arrival_offset=(8, 0),
    )

    with patch("mcp_adapter.gameplay.flare_points_for_warp", return_value=[point]) as concept:
        result = call_tool(
            mcp,
            FLARE_ENDPOINTS_TOOL,
            {"x": 100, "y": 200, "warp_speed": 9, "movement_kind": "gravitonic"},
        )

    assert result.is_error is False
    assert result.structured_content == {
        "endpoints": [
            {
                "waypoint": {"x": 110, "y": 200},
                "arrival": {"x": 109, "y": 201},
                "direct_aim_arrival": {"x": 108, "y": 200},
            }
        ]
    }
    concept.assert_called_once_with(9, FlareMovementKind.GRAVITONIC)


def test_sample_stellar_cartography_returns_sample_at(running_game_info: GameInfo):
    turn = MagicMock()
    payload = {"x": 4, "y": 5, "entries": [{"layer": "nebulae", "lines": ["fog"]}]}
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    with patch("mcp_adapter.gameplay.sample_at", return_value=payload) as concept:
        result = call_tool(mcp, SAMPLE_STELLAR_CARTOGRAPHY_TOOL, {**_SHELL, "x": 4, "y": 5})

    assert result.is_error is False
    assert result.structured_content == payload
    concept.assert_called_once_with(turn, 4, 5)


def test_stellar_cartography_summary_returns_turn_summary(running_game_info: GameInfo):
    turn = MagicMock()
    payload = {"ion_storm_count": 2, "nu_ion_storms": True}
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    with patch(
        "mcp_adapter.gameplay.stellar_cartography_turn_summary",
        return_value=payload,
    ) as concept:
        result = call_tool(mcp, STELLAR_CARTOGRAPHY_SUMMARY_TOOL, _SHELL)

    assert result.is_error is False
    assert result.structured_content == payload
    concept.assert_called_once_with(turn)


def test_disk_proximity_omits_include_and_serializes_hits(running_game_info: GameInfo):
    turn = MagicMock()
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)
    hits = [
        DiskProximityHit(kind="ship", id=11, x=100, y=100),
        DiskProximityHit(kind="nebula", id=33, x=105, y=100, radius=20.0),
    ]

    with patch("mcp_adapter.gameplay.query_disk_proximity", return_value=hits) as concept:
        result = call_tool(
            mcp,
            DISK_PROXIMITY_TOOL,
            {**_SHELL, "x": 100, "y": 100, "radius_ly": 10},
        )

    assert result.is_error is False
    assert result.structured_content == {
        "hits": [
            {"kind": "ship", "id": 11, "x": 100, "y": 100},
            {"kind": "nebula", "id": 33, "x": 105, "y": 100, "radius": 20.0},
        ]
    }
    concept.assert_called_once_with(turn, 100, 100, 10, include=None)


def test_disk_proximity_passes_include_subset(running_game_info: GameInfo):
    turn = MagicMock()
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    with patch("mcp_adapter.gameplay.query_disk_proximity", return_value=[]) as concept:
        result = call_tool(
            mcp,
            DISK_PROXIMITY_TOOL,
            {**_SHELL, "x": 0, "y": 0, "radius_ly": 5, "include": ["ships", "planets"]},
        )

    assert result.is_error is False
    assert result.structured_content == {"hits": []}
    concept.assert_called_once_with(turn, 0, 0, 5, include=["ships", "planets"])


def test_hyperjump_landing_jumping_returns_pre_snap_xy(running_game_info: GameInfo):
    ship = MagicMock()
    ship.id = 42
    ship.hullid = 87
    hull = MagicMock()
    hull.id = 87
    turn = MagicMock()
    turn.ships = [ship]
    turn.hulls = [hull]
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    with (
        patch("mcp_adapter.gameplay.ship_is_performing_hyperjump", return_value=True) as jumping,
        patch("mcp_adapter.gameplay.hyperjump_landing_xy", return_value=(2311, 2441)) as landing,
    ):
        result = call_tool(mcp, HYPERJUMP_LANDING_TOOL, {**_SHELL, "ship_id": 42})

    assert result.is_error is False
    assert result.structured_content == {"jumping": True, "x": 2311, "y": 2441}
    jumping.assert_called_once_with(ship, hull)
    landing.assert_called_once_with(ship)


def test_hyperjump_landing_not_jumping_returns_reason(running_game_info: GameInfo):
    ship = MagicMock()
    ship.id = 42
    ship.hullid = 87
    hull = MagicMock()
    hull.id = 87
    turn = MagicMock()
    turn.ships = [ship]
    turn.hulls = [hull]
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    with (
        patch("mcp_adapter.gameplay.ship_is_performing_hyperjump", return_value=False),
        patch("mcp_adapter.gameplay.hyperjump_landing_xy") as landing,
    ):
        result = call_tool(mcp, HYPERJUMP_LANDING_TOOL, {**_SHELL, "ship_id": 42})

    assert result.is_error is False
    assert result.structured_content == {
        "jumping": False,
        "reason": HYPERJUMP_NOT_JUMPING_REASON,
    }
    landing.assert_not_called()


def test_distance_ly_wraps_euclidean_distance():
    mcp = build_test_mcp()

    with patch("mcp_adapter.gameplay.map_distance_ly", return_value=5.0) as concept:
        result = call_tool(
            mcp,
            DISTANCE_LY_TOOL,
            {"x1": 0, "y1": 0, "x2": 3, "y2": 4},
        )

    assert result.is_error is False
    assert result.structured_content == {"distance_ly": 5.0}
    concept.assert_called_once_with(0, 0, 3, 4)


def test_reachable_planets_filters_routes_to_origin_endpoint(running_game_info: GameInfo):
    planet = MagicMock()
    planet.id = 10
    turn = MagicMock()
    turn.planets = [planet]
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)
    outcome = ConnectionRoutesOutcome(
        routes=[
            {"fromPlanetId": 10, "toPlanetId": 20, "viaFlare": False},
            {"fromPlanetId": 5, "toPlanetId": 10, "viaFlare": True},
            {"fromPlanetId": 1, "toPlanetId": 2, "viaFlare": False},
        ]
    )

    with patch(
        "mcp_adapter.gameplay.connection_routes_with_options",
        return_value=outcome,
    ) as concept:
        result = call_tool(
            mcp,
            REACHABLE_PLANETS_TOOL,
            {
                **_SHELL,
                "from_planet_id": 10,
                "warp_speed": 9,
                "gravitonic_movement": True,
                "flare_mode": "include",
            },
        )

    assert result.is_error is False
    assert result.structured_content == {
        "routes": [
            {"fromPlanetId": 10, "toPlanetId": 20, "viaFlare": False},
            {"fromPlanetId": 5, "toPlanetId": 10, "viaFlare": True},
        ]
    }
    concept.assert_called_once_with(
        turn.planets,
        warp_speed=9,
        gravitonic_movement=True,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=1,
        include_illustrative_routes=False,
    )


def test_reachable_planets_passes_flare_depth(running_game_info: GameInfo):
    planet = MagicMock()
    planet.id = 1
    turn = MagicMock()
    turn.planets = [planet]
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    with patch(
        "mcp_adapter.gameplay.connection_routes_with_options",
        return_value=ConnectionRoutesOutcome(routes=[]),
    ) as concept:
        result = call_tool(
            mcp,
            REACHABLE_PLANETS_TOOL,
            {
                **_SHELL,
                "from_planet_id": 1,
                "warp_speed": 8,
                "gravitonic_movement": False,
                "flare_mode": "only",
                "flare_depth": 3,
            },
        )

    assert result.is_error is False
    assert concept.call_args.kwargs["flare_depth"] == 3
    assert concept.call_args.kwargs["flare_mode"] is FlareConnectionMode.ONLY


def test_turn_scoped_gameplay_tool_returns_needs_ensure_when_turn_missing(
    running_game_info: GameInfo,
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = False
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
    )

    with patch("mcp_adapter.gameplay.coordinate_in_warp_well") as concept:
        result = call_tool(
            mcp,
            POINT_IN_WARP_WELL_TOOL,
            {**_SHELL, "planet_id": 1, "x": 0, "y": 0, "well_kind": "normal"},
        )

    assert result.is_error is False
    assert result.structured_content == NEEDS_ENSURE_RESULT
    turns.get_turn_info.assert_not_called()
    concept.assert_not_called()


def test_turn_scoped_gameplay_tool_refuses_ineligible_perspective(
    running_game_info: GameInfo,
):
    games = MagicMock(spec=GameService)
    games.get_game_info.return_value = running_game_info
    turns = MagicMock(spec=TurnLoadService)
    turns.is_turn_stored.return_value = True
    mcp = build_test_mcp(
        game_service=games,
        turn_load_service=turns,
        resolve_login=resolve_as("arlowat"),
    )

    result = call_tool(
        mcp,
        POINT_IN_WARP_WELL_TOOL,
        {
            "game_id": _GAME_ID,
            "turn": _TURN,
            "perspective": 1,
            "planet_id": 1,
            "x": 0,
            "y": 0,
            "well_kind": "normal",
        },
    )

    assert result.is_error is True
    text = result.content[0].text
    assert "Perspective 1 is not allowed" in text
    turns.is_turn_stored.assert_not_called()
    turns.get_turn_info.assert_not_called()


def test_missing_planet_is_not_found(running_game_info: GameInfo):
    turn = MagicMock()
    turn.planets = []
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    result = call_tool(
        mcp,
        WARP_WELL_CELLS_TOOL,
        {**_SHELL, "planet_id": 99, "well_kind": "normal"},
    )

    assert result.is_error is True
    assert "No planet id 99" in result.content[0].text


def test_missing_ship_is_not_found(running_game_info: GameInfo):
    turn = MagicMock()
    turn.ships = []
    mcp, _, _ = stored_turn_mcp(running_game_info, turn)

    result = call_tool(mcp, HYPERJUMP_LANDING_TOOL, {**_SHELL, "ship_id": 99})

    assert result.is_error is True
    assert "No ship id 99" in result.content[0].text
