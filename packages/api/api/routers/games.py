"""Game info and turn data REST API routes."""

from fastapi import APIRouter, Depends

from api.models.game import GameInfo, TurnInfo
from api.services.game_service import GameService
from api.storage import StorageBackend, get_storage

router = APIRouter(prefix="/v1/games", tags=["games"])


def get_game_service(storage: StorageBackend = Depends(get_storage)) -> GameService:
    return GameService(storage)


@router.get("/{game_id}/info")
def get_game_info(
    game_id: int,
    svc: GameService = Depends(get_game_service),
) -> GameInfo:
    """Return game info for the given game."""
    return svc.get_game_info(game_id)


@router.get("/{game_id}/turns/{turn_number}")
def get_turn_info(
    game_id: int,
    turn_number: int,
    svc: GameService = Depends(get_game_service),
) -> TurnInfo:
    """Return turn data for the given game and turn."""
    return svc.get_turn_info(game_id, turn_number)


@router.get("/{game_id}/turns/{turn_number}/map-base")
def get_map_base(
    game_id: int,
    turn_number: int,
    svc: GameService = Depends(get_game_service),
):
    """Return base-map data (planets as nodes, no edges yet)."""
    return svc.get_map_base(game_id, turn_number)


@router.get("/{game_id}/turns/{turn_number}/analytics/{analytic_id}")
def get_turn_analytics(
    game_id: int,
    turn_number: int,
    analytic_id: str,
    svc: GameService = Depends(get_game_service),
):
    """Return per-analytic map data derived from turn state."""
    return svc.get_turn_analytics(game_id, turn_number, analytic_id)
