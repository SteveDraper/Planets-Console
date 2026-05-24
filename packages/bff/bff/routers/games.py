"""Games list for the console shell: stored game ids from the Core store (shallow read).

This router is mounted on the BFF sub-app at prefix `/games`, so **GET /games** is the path
when using `TestClient(bff.app)` or OpenAPI for the BFF app alone. The root server mounts the
BFF under `/bff`, so the SPA and full-stack docs use **GET /bff/games**.

The handler maps Core store path `games` shallow children to `{"games": [{"id": "..."}, ...]}`.
Each item may include `sectorName` when `games/{id}/info` has a title (`game.name` or
`settings.name`). Titles are memoized in-process per game id so repeated list requests avoid
re-reading every `games/{id}/info`. If `games` does not exist (`NotFoundError` from the store),
returns an empty list.

**POST /games/{game_id}/info** forwards the SPA refresh payload to Core via ``CoreClient``.

**POST /games/{game_id}/turns/ensure** ensures turn data is in storage (Planets.nu loadturn
when missing), using the same credential rules as game info refresh.

**Warp wells** -- turn-scoped concept routes delegate to shared Core handlers via ``CoreClient``.
"""

from __future__ import annotations

from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)
from api.transport.game_info_update import GameInfoUpdateRequest
from api.transport.turn_ensure import TurnEnsureRequest
from fastapi import APIRouter, Path, Query

from bff.core_client import get_core_client
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)
from bff.transport.game_responses import BffGameInfoResponse, BffTurnInfoResponse

router = APIRouter()


@router.get("")
def list_stored_games(
    include: IncludeDiagnostics = False,
):
    """Return game ids present under store path `games` (next-hop segment names).

    Route: **GET /games** on the BFF app; **GET /bff/games** when the BFF is mounted at `/bff`.

    Uses the same shallow enumeration as GET /api/v1/store/games?view=shallow.
    """
    core = get_core_client()
    root = optional_request_root(include, "GET", "/games", handler="list_stored_games")
    body = with_timed_child(root, "list_stored_games", "total", core.list_stored_games)
    return finish_response(body, root)


@router.get("/{game_id}/turns/{turn_number}/stored-perspectives")
def get_stored_turn_perspectives(
    game_id: int,
    turn_number: int = Path(..., ge=1),
    include: IncludeDiagnostics = False,
) -> object:
    """Return perspective slots that already have turn data in storage (no Planets.nu)."""
    core = get_core_client()
    root = optional_request_root(
        include,
        "GET",
        f"/games/{game_id}/turns/{turn_number}/stored-perspectives",
        gameId=game_id,
        turn=turn_number,
        handler="get_stored_turn_perspectives",
    )
    result = with_timed_child(
        root,
        "get_stored_turn_perspectives",
        "total",
        lambda: core.list_stored_turn_perspectives(game_id, turn_number),
    )
    return finish_response(result, root)


@router.get("/{game_id}/info", response_model=BffGameInfoResponse)
def get_stored_game_info(game_id: int, include: IncludeDiagnostics = False) -> object:
    """Return game info already in storage (no Planets.nu refresh)."""
    core = get_core_client()
    root = optional_request_root(
        include,
        "GET",
        f"/games/{game_id}/info",
        gameId=game_id,
        handler="get_stored_game_info",
    )
    result = with_timed_child(
        root,
        "get_stored_game_info",
        "total",
        lambda: core.get_stored_game_info(game_id),
    )
    return finish_response(result, root)


@router.post("/{game_id}/info", response_model=BffGameInfoResponse)
def post_game_info(
    game_id: int,
    body: GameInfoUpdateRequest,
    include: IncludeDiagnostics = False,
) -> object:
    """Refresh game info from Planets.nu (`refresh`); returns updated `GameInfo`."""
    core = get_core_client()
    root = optional_request_root(
        include,
        "POST",
        f"/games/{game_id}/info",
        gameId=game_id,
        handler="post_game_info",
    )
    updated = with_timed_child(
        root,
        "post_game_info",
        "total",
        lambda: core.refresh_game_info(game_id, body),
    )
    return finish_response(updated, root)


@router.post("/{game_id}/turns/ensure", response_model=BffTurnInfoResponse)
def post_ensure_turn(
    game_id: int,
    body: TurnEnsureRequest,
    include: IncludeDiagnostics = False,
) -> object:
    """Ensure turn data exists in storage; fetch from Planets.nu when absent."""
    core = get_core_client()
    root = optional_request_root(
        include,
        "POST",
        f"/games/{game_id}/turns/ensure",
        gameId=game_id,
        turn=body.turn,
        perspective=body.perspective,
        handler="post_ensure_turn",
    )
    result = with_timed_child(
        root,
        "post_ensure_turn",
        "total",
        lambda: core.ensure_turn(game_id, body),
    )
    return finish_response(result, root)


@router.post(
    "/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/coordinate-in-well",
    response_model=CoordinateInWarpWellResponse,
)
def post_warp_well_coordinate_in_well(
    game_id: int,
    perspective: int,
    turn_number: int,
    body: CoordinateInWarpWellRequest,
    include: IncludeDiagnostics = False,
) -> object:
    """Turn-scoped warp-well point test via ``CoreClient`` (shared handler with Core REST)."""
    core = get_core_client()
    bff_path = (
        f"/games/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/coordinate-in-well"
    )
    root = optional_request_root(
        include,
        "POST",
        bff_path,
        gameId=game_id,
        perspective=perspective,
        turn=turn_number,
        planetId=body.planet_id,
        handler="post_warp_well_coordinate_in_well",
    )
    result = with_timed_child(
        root,
        "post_warp_well_coordinate_in_well",
        "total",
        lambda: core.warp_well_coordinate_in_well(game_id, perspective, turn_number, body),
    )
    return finish_response(result, root)


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
    include: IncludeDiagnostics = False,
) -> object:
    """Turn-scoped warp-well cells via ``CoreClient`` (shared handler with Core REST)."""
    core = get_core_client()
    bff_path = f"/games/{game_id}/{perspective}/turns/{turn_number}/concepts/warp-wells/cells"
    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        perspective=perspective,
        turn=turn_number,
        planetId=planet_id,
        wellType=well_type.value,
        handler="get_warp_well_cells",
    )
    result = with_timed_child(
        root,
        "get_warp_well_cells",
        "total",
        lambda: core.warp_well_cells(game_id, perspective, turn_number, planet_id, well_type),
    )
    return finish_response(result, root)
