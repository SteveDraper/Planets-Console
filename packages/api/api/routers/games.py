"""Game info and turn data REST API routes."""

from fastapi import APIRouter, Depends, Query

from api.concepts.planet_connections import FlareConnectionMode
from api.models.game import GameInfo, TurnInfo
from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.storage import StorageBackend, get_storage
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams

router = APIRouter(prefix="/v1/games", tags=["games"])


def get_planets_client() -> PlanetsNuClient:
    return PlanetsNuClient.from_config()


def get_game_service(storage: StorageBackend = Depends(get_storage)) -> GameService:
    return GameService(storage)


@router.get("/{game_id}/info")
def get_game_info(
    game_id: int,
    svc: GameService = Depends(get_game_service),
) -> GameInfo:
    """Return game info for the given game."""
    return svc.get_game_info(game_id)


@router.post("/{game_id}/info")
def post_game_info(
    game_id: int,
    body: GameInfoUpdateRequest,
    svc: GameService = Depends(get_game_service),
    planets: PlanetsNuClient = Depends(get_planets_client),
) -> GameInfo:
    """Apply an update operation (e.g. refresh from Planets.nu) and return stored game info."""
    return svc.update_game_info(game_id, body, planets)


@router.post("/{game_id}/{perspective}/turns/{turn_number}/ensure")
def post_ensure_turn(
    game_id: int,
    perspective: int,
    turn_number: int,
    body: RefreshGameInfoParams,
    svc: GameService = Depends(get_game_service),
    planets: PlanetsNuClient = Depends(get_planets_client),
) -> TurnInfo:
    """Load turn from Planets.nu when missing in storage; return stored turn data."""
    return svc.ensure_turn_loaded(game_id, perspective, turn_number, body, planets)


@router.get("/{game_id}/{perspective}/turns/{turn_number}")
def get_turn_info(
    game_id: int,
    perspective: int,
    turn_number: int,
    svc: GameService = Depends(get_game_service),
) -> TurnInfo:
    """Return turn data for the given game, player perspective, and turn."""
    return svc.get_turn_info(game_id, perspective, turn_number)


@router.get("/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}")
def get_turn_analytics(
    game_id: int,
    perspective: int,
    turn_number: int,
    analytic_id: str,
    warp_speed: int | None = Query(None, ge=1, le=9, alias="warpSpeed"),
    gravitonic_movement: bool = Query(False, alias="gravitonicMovement"),
    flare_mode: FlareConnectionMode = Query(FlareConnectionMode.OFF, alias="flareMode"),
    svc: GameService = Depends(get_game_service),
):
    """Return per-analytic map data derived from turn state."""
    return svc.get_turn_analytics(
        game_id,
        perspective,
        turn_number,
        analytic_id,
        connection_warp_speed=warp_speed,
        connection_gravitonic_movement=gravitonic_movement,
        connection_flare_mode=flare_mode,
    )
