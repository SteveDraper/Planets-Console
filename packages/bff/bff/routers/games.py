"""Games list for the console shell: stored game ids from the Core store (shallow read).

This router is mounted on the BFF sub-app at prefix `/games`, so **GET /games** is the path
when using `TestClient(bff.app)` or OpenAPI for the BFF app alone. The root server mounts the
BFF under `/bff`, so the SPA and full-stack docs use **GET /bff/games**.

The handler maps Core store path `games` shallow children to `{"games": [{"id": "..."}]}`.
If `games` does not exist (`NotFoundError` from the store), returns an empty list.

**POST /games/{game_id}/info** forwards the SPA refresh payload to Core `GameService` (same
contract as Core **POST /api/v1/games/{game_id}/info**): load game info from Planets.nu and
replace stored game info.

**POST /games/{game_id}/turns/ensure** ensures turn data is in storage (Planets.nu loadturn
when missing), using the same credential rules as game info refresh.

**Warp wells** -- ``POST .../concepts/warp-wells/coordinate-in-well`` and
``GET .../concepts/warp-wells/cells`` mirror Core ``GameService`` (same paths as Core under
``/v1/games``). Shallow calls today; replaceable with HTTP to Core later.
"""

from api.concepts.warp_well import WarpWellKind
from api.errors import NotFoundError, PlanetsConsoleError
from api.models.game import GameInfo
from api.planets_nu import PlanetsNuClient
from api.services.game_service import GameService
from api.services.store_service import StoreService
from api.storage import get_storage
from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)
from api.transport.game_info_update import GameInfoUpdateRequest, RefreshGameInfoParams
from api.transport.turn_ensure import TurnEnsureRequest
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("")
def list_stored_games():
    """Return game ids present under store path `games` (next-hop segment names).

    Route: **GET /games** on the BFF app; **GET /bff/games** when the BFF is mounted at `/bff`.

    Uses the same shallow enumeration as GET /api/v1/store/games?view=shallow.
    """
    svc = StoreService(get_storage())
    try:
        shallow = svc.read_shallow("games")
    except NotFoundError:
        return {"games": []}
    children = shallow.get("children") or []
    return {"games": [{"id": str(child)} for child in children]}


@router.post("/{game_id}/info")
def post_game_info(game_id: int, body: GameInfoUpdateRequest) -> GameInfo:
    """Refresh game info from Planets.nu (`refresh`); returns updated `GameInfo`."""
    storage = get_storage()
    svc = GameService(storage)
    planets = PlanetsNuClient.from_config()
    try:
        return svc.update_game_info(game_id, body, planets)
    except PlanetsConsoleError as exc:
        raise HTTPException(
            status_code=getattr(exc, "http_error", 500),
            detail=str(exc),
        ) from exc


@router.post("/{game_id}/turns/ensure")
def post_ensure_turn(game_id: int, body: TurnEnsureRequest):
    """Ensure turn data exists in storage; fetch from Planets.nu when absent."""
    storage = get_storage()
    svc = GameService(storage)
    planets = PlanetsNuClient.from_config()
    params = RefreshGameInfoParams(username=body.username, password=body.password)
    try:
        return svc.ensure_turn_loaded(game_id, body.perspective, body.turn, params, planets)
    except PlanetsConsoleError as exc:
        raise HTTPException(
            status_code=getattr(exc, "http_error", 500),
            detail=str(exc),
        ) from exc


@router.post(
    "/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/coordinate-in-well",
    response_model=CoordinateInWarpWellResponse,
)
def post_warp_well_coordinate_in_well(
    game_id: int,
    perspective: int,
    turn_number: int,
    body: CoordinateInWarpWellRequest,
) -> CoordinateInWarpWellResponse:
    """Shallow forward to Core ``GameService`` (same contract as Core REST)."""
    storage = get_storage()
    svc = GameService(storage)
    kind = WarpWellKind(body.well_type.value)
    try:
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
    except PlanetsConsoleError as exc:
        raise HTTPException(
            status_code=getattr(exc, "http_error", 500),
            detail=str(exc),
        ) from exc


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
) -> WarpWellCellsResponse:
    """Shallow forward to Core ``GameService`` (same contract as Core REST)."""
    storage = get_storage()
    svc = GameService(storage)
    kind = WarpWellKind(well_type.value)
    try:
        cells = svc.warp_well_cells(game_id, perspective, turn_number, planet_id, kind)
        return WarpWellCellsResponse(cells=cells)
    except PlanetsConsoleError as exc:
        raise HTTPException(
            status_code=getattr(exc, "http_error", 500),
            detail=str(exc),
        ) from exc
