"""Shared turn-scoped warp-well route logic for Core and BFF callers."""

from api.concepts.warp_well import WarpWellKind
from api.services.game_service import GameService
from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)


def coordinate_in_well(
    svc: GameService,
    game_id: int,
    perspective: int,
    turn_number: int,
    body: CoordinateInWarpWellRequest,
) -> CoordinateInWarpWellResponse:
    """Return whether ``(map_x, map_y)`` lies in the given warp well of the planet."""
    kind = WarpWellKind(body.well_type.value)
    inside = svc.warp_well_coordinate_in_well(
        game_id,
        perspective,
        turn_number,
        body.planet_id,
        body.map_x,
        body.map_y,
        kind,
    )
    return CoordinateInWarpWellResponse(inside=inside)


def warp_well_cells(
    svc: GameService,
    game_id: int,
    perspective: int,
    turn_number: int,
    planet_id: int,
    well_type: WarpWellTypeParam,
) -> WarpWellCellsResponse:
    """Return map cell indices whose centers lie in the given warp well."""
    kind = WarpWellKind(well_type.value)
    cells = svc.warp_well_cells(game_id, perspective, turn_number, planet_id, kind)
    return WarpWellCellsResponse(cells=cells)
