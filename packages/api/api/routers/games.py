"""Game info and turn data REST API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from api.models.game import GameInfo, TurnInfo
from api.planets_nu import PlanetsNuClient
from api.services.deps import (
    get_game_service,
    get_load_all_turns_service,
    get_turn_analytic_service,
    get_turn_load_service,
)
from api.services.game_service import GameService
from api.services.load_all_turns import LoadAllTurnsService
from api.services.turn_analytic_service import TurnAnalyticService
from api.services.turn_load_service import TurnLoadService
from api.transport.connections_options import (
    DEFAULT_FLARE_DEPTH,
    FLARE_DEPTH_DESCRIPTION,
    FLARE_DEPTH_QUERY,
    FLARE_MODE_QUERY,
    GRAVITONIC_MOVEMENT_QUERY,
    INCLUDE_ILLUSTRATIVE_ROUTES_DESCRIPTION,
    INCLUDE_ILLUSTRATIVE_ROUTES_QUERY,
    WARP_SPEED_QUERY,
    FlareConnectionMode,
)
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams
from api.transport.load_all_turns import (
    LoadAllTurnsRequest,
    LoadAllTurnsStatusResponse,
    stream_load_all_turns,
)

router = APIRouter(prefix="/v1/games", tags=["games"])


def get_planets_client() -> PlanetsNuClient:
    return PlanetsNuClient.from_config()


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


@router.get("/{game_id}/turns/load-all-status", response_model=LoadAllTurnsStatusResponse)
def get_load_all_turns_status(
    game_id: int,
    username: Annotated[str, Query()] = "",
    load_all: LoadAllTurnsService = Depends(get_load_all_turns_service),
) -> LoadAllTurnsStatusResponse:
    """Report whether storage already has every turn expected after a bulk load."""
    return load_all.load_all_turns_status_for_user(game_id, username)


@router.post("/{game_id}/turns/load-all/stream")
def post_load_all_turns_stream(
    game_id: int,
    body: LoadAllTurnsRequest,
    load_all: LoadAllTurnsService = Depends(get_load_all_turns_service),
    planets: PlanetsNuClient = Depends(get_planets_client),
) -> StreamingResponse:
    """Load all turns, streaming NDJSON progress events."""
    return StreamingResponse(
        stream_load_all_turns(lambda: load_all.iter_load_all_turns(game_id, body, planets)),
        media_type="application/x-ndjson",
    )


@router.post("/{game_id}/{perspective}/turns/{turn_number}/ensure")
def post_ensure_turn(
    game_id: int,
    perspective: int,
    turn_number: int,
    body: RefreshGameInfoParams,
    turns: TurnLoadService = Depends(get_turn_load_service),
    planets: PlanetsNuClient = Depends(get_planets_client),
) -> TurnInfo:
    """Load turn from Planets.nu when missing in storage; return stored turn data."""
    return turns.ensure_turn_loaded(game_id, perspective, turn_number, body, planets)


@router.get("/{game_id}/{perspective}/turns/{turn_number}")
def get_turn_info(
    game_id: int,
    perspective: int,
    turn_number: int,
    turns: TurnLoadService = Depends(get_turn_load_service),
) -> TurnInfo:
    """Return turn data for the given game, player perspective, and turn."""
    return turns.get_turn_info(game_id, perspective, turn_number)


@router.get("/{game_id}/{perspective}/turns/{turn_number}/analytics/scores/inference")
def get_scores_row_inference(
    game_id: int,
    perspective: int,
    turn_number: int,
    player_id: int = Query(..., alias="playerId", ge=0),
    analytics: TurnAnalyticService = Depends(get_turn_analytic_service),
):
    """Return military score build inference for one scoreboard row."""
    return analytics.get_scores_row_inference(
        game_id,
        perspective,
        turn_number,
        player_id,
    )


@router.get("/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}")
def get_turn_analytics(
    game_id: int,
    perspective: int,
    turn_number: int,
    analytic_id: str,
    warp_speed: int | None = Query(None, ge=1, le=9, alias=WARP_SPEED_QUERY),
    gravitonic_movement: bool = Query(False, alias=GRAVITONIC_MOVEMENT_QUERY),
    flare_mode: FlareConnectionMode = Query(FlareConnectionMode.OFF, alias=FLARE_MODE_QUERY),
    flare_depth: int = Query(
        DEFAULT_FLARE_DEPTH,
        ge=1,
        le=3,
        alias=FLARE_DEPTH_QUERY,
        description=FLARE_DEPTH_DESCRIPTION,
    ),
    include_illustrative_routes: bool = Query(
        False,
        alias=INCLUDE_ILLUSTRATIVE_ROUTES_QUERY,
        description=INCLUDE_ILLUSTRATIVE_ROUTES_DESCRIPTION,
    ),
    analytics: TurnAnalyticService = Depends(get_turn_analytic_service),
):
    """Return per-analytic map data derived from turn state."""
    return analytics.get_turn_analytics(
        game_id,
        perspective,
        turn_number,
        analytic_id,
        connection_warp_speed=warp_speed,
        connection_gravitonic_movement=gravitonic_movement,
        connection_flare_mode=flare_mode,
        connection_flare_depth=flare_depth,
        connection_include_illustrative_routes=include_illustrative_routes,
    )
