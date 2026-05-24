"""Turn-scoped game concept endpoints (pure rules live in ``api.concepts``)."""

from fastapi import APIRouter, Depends, Query

from api.handlers.warp_well import coordinate_in_well, warp_well_cells
from api.services.deps import get_turn_concept_service
from api.services.turn_concept_service import TurnConceptService
from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)

router = APIRouter(prefix="/v1/games", tags=["game-concepts"])


@router.post(
    "/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/coordinate-in-well",
    response_model=CoordinateInWarpWellResponse,
)
def post_warp_well_coordinate_in_well(
    game_id: int,
    perspective: int,
    turn_number: int,
    body: CoordinateInWarpWellRequest,
    svc: TurnConceptService = Depends(get_turn_concept_service),
) -> CoordinateInWarpWellResponse:
    """Return whether ``(map_x, map_y)`` lies in the given warp well of the planet."""
    return coordinate_in_well(svc, game_id, perspective, turn_number, body)


@router.get(
    "/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/cells",
    response_model=WarpWellCellsResponse,
)
def get_warp_well_cells(
    game_id: int,
    perspective: int,
    turn_number: int,
    planet_id: int = Query(..., ge=1),
    well_type: WarpWellTypeParam = Query(...),
    svc: TurnConceptService = Depends(get_turn_concept_service),
) -> WarpWellCellsResponse:
    """Return map cell indices whose centers lie in the given warp well."""
    return warp_well_cells(svc, game_id, perspective, turn_number, planet_id, well_type)
