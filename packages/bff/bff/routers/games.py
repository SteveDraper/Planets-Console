"""Games routes for the console shell.

Mounted at prefix `/games` on the BFF sub-app (**GET /games**). The root server mounts the
BFF at `/bff`, so the SPA uses **GET /bff/games**.

Routes delegate to the process-singleton ``CoreClient`` (``get_core_client``), which calls
Core services only -- no direct storage access in this router.

**GET /games** uses ``GameService.list_stored_games()``: stored game ids under ``games/``,
optional ``sectorName`` from in-process memo or ``games/{id}/info`` (empty list when the
``games`` prefix is absent).

**POST /games/{game_id}/info** refreshes game info from Planets.nu. **POST .../turns/ensure**
loads a turn when missing. Warp-well and Stellar Cartography routes use shared Core handlers.
"""

from __future__ import annotations

from typing import Annotated

from api.transport.concept_stellar_cartography import StellarCartographySampleResponse
from api.transport.concept_warp_well import (
    CoordinateInWarpWellRequest,
    CoordinateInWarpWellResponse,
    WarpWellCellsResponse,
    WarpWellTypeParam,
)
from api.transport.game_info_update import GameInfoUpdateRequest
from api.transport.load_all_turns import stream_load_all_turns
from api.transport.turn_ensure import TurnEnsureRequest
from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse

from bff.core_client import CoreClient, get_core_client
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)
from bff.transport.game_responses import (
    BffGameInfoResponse,
    BffTurnInfoResponse,
    LoadAllTurnsRequest,
    LoadAllTurnsStatusResponse,
    StellarCartographyTurnSummaryResponse,
    StoredTurnPerspectivesResponse,
)

router = APIRouter()

CoreClientDep = Annotated[CoreClient, Depends(get_core_client)]


@router.get("")
def list_stored_games(
    include: IncludeDiagnostics = False,
    *,
    core: CoreClientDep,
):
    """Return stored game ids (optional sector names) via Core ``GameService``.

    Route: **GET /games** on the BFF app; **GET /bff/games** when mounted at `/bff`.
    """
    root = optional_request_root(include, "GET", "/games", handler="list_stored_games")
    body = with_timed_child(root, "list_stored_games", "total", core.list_stored_games)
    return finish_response(body, root)


@router.get(
    "/{game_id}/turns/{turn_number}/stored-perspectives",
    response_model=StoredTurnPerspectivesResponse,
)
def get_stored_turn_perspectives(
    game_id: int,
    turn_number: int = Path(..., ge=1),
    include: IncludeDiagnostics = False,
    *,
    core: CoreClientDep,
) -> object:
    """Return perspective slots that already have turn data in storage (no Planets.nu)."""
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
def get_stored_game_info(
    game_id: int,
    include: IncludeDiagnostics = False,
    *,
    core: CoreClientDep,
) -> object:
    """Return game info already in storage (no Planets.nu refresh)."""
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
    *,
    core: CoreClientDep,
) -> object:
    """Refresh game info from Planets.nu (`refresh`); returns updated `GameInfo`."""
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


@router.get("/{game_id}/turns/load-all-status", response_model=LoadAllTurnsStatusResponse)
def get_load_all_turns_status(
    game_id: int,
    username: Annotated[str, Query()] = "",
    include: IncludeDiagnostics = False,
    *,
    core: CoreClientDep,
) -> object:
    """Whether storage already has every turn expected after a bulk load."""
    root = optional_request_root(
        include,
        "GET",
        f"/games/{game_id}/turns/load-all-status",
        gameId=game_id,
        handler="get_load_all_turns_status",
    )
    result = with_timed_child(
        root,
        "get_load_all_turns_status",
        "total",
        lambda: core.load_all_turns_status(game_id, username),
    )
    return finish_response(result, root)


@router.post(
    "/{game_id}/turns/load-all/stream",
    responses={
        200: {
            "description": "NDJSON stream of progress, complete, and error events.",
            "content": {
                "application/x-ndjson": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/LoadAllStreamProgressEvent"},
                            {"$ref": "#/components/schemas/LoadAllStreamCompleteEvent"},
                            {"$ref": "#/components/schemas/LoadAllStreamErrorEvent"},
                        ]
                    }
                }
            },
        }
    },
)
def post_load_all_turns_stream(
    game_id: int,
    body: LoadAllTurnsRequest,
    *,
    core: CoreClientDep,
) -> StreamingResponse:
    """Load all turns, streaming NDJSON progress events."""
    return StreamingResponse(
        stream_load_all_turns(
            lambda: core.iter_load_all_turns(game_id, body.username, body.password)
        ),
        media_type="application/x-ndjson",
    )


@router.post("/{game_id}/turns/ensure", response_model=BffTurnInfoResponse)
def post_ensure_turn(
    game_id: int,
    body: TurnEnsureRequest,
    include: IncludeDiagnostics = False,
    *,
    core: CoreClientDep,
) -> object:
    """Ensure turn data exists in storage; fetch from Planets.nu when absent."""
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
    *,
    core: CoreClientDep,
) -> object:
    """Turn-scoped warp-well point test via ``CoreClient`` (shared handler with Core REST)."""
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
    *,
    core: CoreClientDep,
) -> object:
    """Turn-scoped warp-well cells via ``CoreClient`` (shared handler with Core REST)."""
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


@router.get(
    "/{game_id}/{perspective}/turns/{turn_number}/concepts/stellar-cartography/sample",
    response_model=StellarCartographySampleResponse,
)
def get_stellar_cartography_sample(
    game_id: int,
    perspective: int,
    turn_number: int,
    x: int = Query(..., ge=0),
    y: int = Query(..., ge=0),
    include: IncludeDiagnostics = False,
    *,
    core: CoreClientDep,
) -> object:
    """Turn-scoped Stellar Cartography cell sample via ``CoreClient``."""
    bff_path = (
        f"/games/{game_id}/{perspective}/turns/{turn_number}/concepts/stellar-cartography/sample"
    )
    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        perspective=perspective,
        turn=turn_number,
        x=x,
        y=y,
        handler="get_stellar_cartography_sample",
    )
    result = with_timed_child(
        root,
        "get_stellar_cartography_sample",
        "total",
        lambda: core.stellar_cartography_sample(game_id, perspective, turn_number, x, y),
    )
    return finish_response(result, root)


@router.get(
    "/{game_id}/{perspective}/turns/{turn_number}/concepts/stellar-cartography/summary",
    response_model=StellarCartographyTurnSummaryResponse,
)
def get_stellar_cartography_turn_summary(
    game_id: int,
    perspective: int,
    turn_number: int,
    include: IncludeDiagnostics = False,
    *,
    core: CoreClientDep,
) -> object:
    """Turn-scoped lightweight Stellar Cartography facts via ``CoreClient``."""
    bff_path = (
        f"/games/{game_id}/{perspective}/turns/{turn_number}/concepts/stellar-cartography/summary"
    )
    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        perspective=perspective,
        turn=turn_number,
        handler="get_stellar_cartography_turn_summary",
    )

    def load_summary() -> StellarCartographyTurnSummaryResponse:
        summary = core.stellar_cartography_turn_summary(game_id, perspective, turn_number)
        return StellarCartographyTurnSummaryResponse(
            ionStormCount=summary.ion_storm_count,
            nuIonStorms=summary.nu_ion_storms,
        )

    result = with_timed_child(
        root,
        "get_stellar_cartography_turn_summary",
        "total",
        load_summary,
    )
    return finish_response(result, root)
