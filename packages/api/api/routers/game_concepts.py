"""Turn-scoped game concept endpoints (pure rules live in ``api.concepts``)."""

from fastapi import APIRouter, Depends, Query

from api.concepts.warp_well import WarpWellKind
from api.services.game_service import GameService
from api.storage import StorageBackend, get_storage
from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)

router = APIRouter(prefix="/v1/games", tags=["game-concepts"])


def get_game_service(storage: StorageBackend = Depends(get_storage)) -> GameService:
    return GameService(storage)


@router.post(
    "/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/coordinate-in-well",
    response_model=CoordinateInWarpWellResponse,
)
def post_warp_well_coordinate_in_well(
    game_id: int,
    perspective: int,
    turn_number: int,
    body: CoordinateInWarpWellRequest,
    svc: GameService = Depends(get_game_service),
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
    svc: GameService = Depends(get_game_service),
) -> WarpWellCellsResponse:
    """Return map cell indices whose centers lie in the given warp well."""
    kind = WarpWellKind(well_type.value)
    cells = svc.warp_well_cells(game_id, perspective, turn_number, planet_id, kind)
    return WarpWellCellsResponse(cells=cells)
