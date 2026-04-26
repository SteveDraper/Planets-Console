"""Games list for the console shell: stored game ids from the Core store (shallow read).

This router is mounted on the BFF sub-app at prefix `/games`, so **GET /games** is the path
when using `TestClient(bff.app)` or OpenAPI for the BFF app alone. The root server mounts the
BFF under `/bff`, so the SPA and full-stack docs use **GET /bff/games**.

The handler maps Core store path `games` shallow children to `{"games": [{"id": "..."}, ...]}`.
Each item may include `sectorName` when `games/{id}/info` has a title (`game.name` or
`settings.name`). Titles are memoized in-process per game id so repeated list requests avoid
re-reading every `games/{id}/info`. If `games` does not exist (`NotFoundError` from the store),
returns an empty list.

**POST /games/{game_id}/info** forwards the SPA refresh payload to Core `GameService` (same
contract as Core **POST /api/v1/games/{game_id}/info**): load game info from Planets.nu and
replace stored game info.

**POST /games/{game_id}/turns/ensure** ensures turn data is in storage (Planets.nu loadturn
when missing), using the same credential rules as game info refresh.

**Warp wells** -- ``POST .../concepts/warp-wells/coordinate-in-well`` and
``GET .../concepts/warp-wells/cells`` mirror Core ``GameService`` (same paths as Core under
``/v1/games``). Shallow calls today; replaceable with HTTP to Core later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from typing import Any, get_type_hints

from api.concepts.warp_well import WarpWellKind
from api.errors import NotFoundError, PlanetsConsoleError
from api.models.game import GameInfo, TurnInfo
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
from pydantic import BaseModel, ConfigDict, Field, create_model, model_serializer

from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)

router = APIRouter()


def _bff_dataclass_response_with_diagnostics(
    pydantic_model_name: str,
    dataclass_type: type,
) -> type[BaseModel]:
    """Pydantic model mirroring ``dataclass_type`` with optional BFF ``diagnostics`` (OpenAPI)."""
    hints = get_type_hints(dataclass_type, include_extras=True)
    field_defs: dict = {f.name: (hints[f.name], Field()) for f in fields(dataclass_type)}
    field_defs["diagnostics"] = (
        dict[str, Any] | None,
        Field(
            default=None,
            description="Request timing tree; present when includeDiagnostics=true.",
        ),
    )

    class _OmitNullDiagnosticsBase(BaseModel):
        @model_serializer(mode="wrap")
        def _omit_diagnostics(self, handler: Callable[[BaseModel], Any]) -> Any:
            data = handler(self)
            if isinstance(data, dict) and data.get("diagnostics") is None:
                out = dict(data)
                out.pop("diagnostics", None)
                return out
            return data

    return create_model(
        pydantic_model_name,
        __base__=_OmitNullDiagnosticsBase,
        __config__=ConfigDict(),
        __module__=__name__,
        **field_defs,
    )


BffGameInfoResponse = _bff_dataclass_response_with_diagnostics("BffGameInfoResponse", GameInfo)
BffTurnInfoResponse = _bff_dataclass_response_with_diagnostics("BffTurnInfoResponse", TurnInfo)

_sector_title_by_stored_game_id: dict[str, str | None] = {}


def _sector_title_from_stored_info_payload(raw: object) -> str | None:
    """Best-effort sector title from a stored `games/{{id}}/info` JSON object."""
    if not isinstance(raw, dict):
        return None
    for key in ("game", "settings"):
        block = raw.get(key)
        if isinstance(block, dict):
            name = block.get("name")
            if isinstance(name, str):
                trimmed = name.strip()
                if trimmed:
                    return trimmed
    return None


def _sector_title_from_game_info(info: GameInfo) -> str | None:
    """Match `_sector_title_from_stored_info_payload` precedence using a loaded `GameInfo`."""
    for name in (info.game.name, info.settings.name):
        if isinstance(name, str):
            trimmed = name.strip()
            if trimmed:
                return trimmed
    return None


def _resolved_sector_title_for_listed_game(svc: StoreService, game_id: str) -> str | None:
    """Sector title for the games list; uses a per-process cache to avoid repeated store reads."""
    cached = _sector_title_by_stored_game_id.get(game_id)
    if cached is not None or game_id in _sector_title_by_stored_game_id:
        return cached
    try:
        raw = svc.read(f"games/{game_id}/info")
    except NotFoundError:
        _sector_title_by_stored_game_id[game_id] = None
        return None
    title = _sector_title_from_stored_info_payload(raw)
    _sector_title_by_stored_game_id[game_id] = title
    return title


def _games_list_body(svc: StoreService) -> dict:
    try:
        shallow = svc.read_shallow("games")
    except NotFoundError:
        return {"games": []}
    children = shallow.get("children") or []
    games: list[dict[str, str]] = []
    for child in children:
        gid = str(child)
        entry: dict[str, str] = {"id": gid}
        sector = _resolved_sector_title_for_listed_game(svc, gid)
        if sector is not None:
            entry["sectorName"] = sector
        games.append(entry)
    return {"games": games}


@router.get("")
def list_stored_games(
    include: IncludeDiagnostics = False,
):
    """Return game ids present under store path `games` (next-hop segment names).

    Route: **GET /games** on the BFF app; **GET /bff/games** when the BFF is mounted at `/bff`.

    Uses the same shallow enumeration as GET /api/v1/store/games?view=shallow.
    """
    svc = StoreService(get_storage())
    root = optional_request_root(include, "GET", "/games", handler="list_stored_games")
    body = with_timed_child(root, "list_stored_games", "total", lambda: _games_list_body(svc))
    return finish_response(body, root)


@router.get("/{game_id}/info", response_model=BffGameInfoResponse)
def get_stored_game_info(game_id: int, include: IncludeDiagnostics = False) -> object:
    """Return game info already in storage (no Planets.nu refresh)."""
    storage = get_storage()
    svc = GameService(storage)
    root = optional_request_root(
        include,
        "GET",
        f"/games/{game_id}/info",
        gameId=game_id,
        handler="get_stored_game_info",
    )

    def work() -> GameInfo:
        try:
            return svc.get_game_info(game_id)
        except PlanetsConsoleError as exc:
            raise HTTPException(
                status_code=getattr(exc, "http_error", 500),
                detail=str(exc),
            ) from exc

    result = with_timed_child(root, "get_stored_game_info", "total", work)
    return finish_response(result, root)


@router.post("/{game_id}/info", response_model=BffGameInfoResponse)
def post_game_info(
    game_id: int,
    body: GameInfoUpdateRequest,
    include: IncludeDiagnostics = False,
) -> object:
    """Refresh game info from Planets.nu (`refresh`); returns updated `GameInfo`."""
    storage = get_storage()
    svc = GameService(storage)
    planets = PlanetsNuClient.from_config()
    root = optional_request_root(
        include,
        "POST",
        f"/games/{game_id}/info",
        gameId=game_id,
        handler="post_game_info",
    )

    def work() -> GameInfo:
        try:
            return svc.update_game_info(game_id, body, planets)
        except PlanetsConsoleError as exc:
            raise HTTPException(
                status_code=getattr(exc, "http_error", 500),
                detail=str(exc),
            ) from exc

    updated = with_timed_child(root, "post_game_info", "total", work)
    _sector_title_by_stored_game_id[str(game_id)] = _sector_title_from_game_info(updated)
    return finish_response(updated, root)


@router.post("/{game_id}/turns/ensure", response_model=BffTurnInfoResponse)
def post_ensure_turn(
    game_id: int,
    body: TurnEnsureRequest,
    include: IncludeDiagnostics = False,
) -> object:
    """Ensure turn data exists in storage; fetch from Planets.nu when absent."""
    storage = get_storage()
    svc = GameService(storage)
    planets = PlanetsNuClient.from_config()
    params = RefreshGameInfoParams(username=body.username, password=body.password)
    root = optional_request_root(
        include,
        "POST",
        f"/games/{game_id}/turns/ensure",
        gameId=game_id,
        turn=body.turn,
        perspective=body.perspective,
        handler="post_ensure_turn",
    )

    def work():
        try:
            return svc.ensure_turn_loaded(game_id, body.perspective, body.turn, params, planets)
        except PlanetsConsoleError as exc:
            raise HTTPException(
                status_code=getattr(exc, "http_error", 500),
                detail=str(exc),
            ) from exc

    result = with_timed_child(root, "post_ensure_turn", "total", work)
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
    """Shallow forward to Core ``GameService`` (same contract as Core REST)."""
    storage = get_storage()
    svc = GameService(storage)
    kind = WarpWellKind(body.well_type.value)
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

    def work() -> CoordinateInWarpWellResponse:
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

    result = with_timed_child(root, "post_warp_well_coordinate_in_well", "total", work)
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
    """Shallow forward to Core ``GameService`` (same contract as Core REST)."""
    storage = get_storage()
    svc = GameService(storage)
    kind = WarpWellKind(well_type.value)
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

    def work() -> WarpWellCellsResponse:
        try:
            cells = svc.warp_well_cells(game_id, perspective, turn_number, planet_id, kind)
            return WarpWellCellsResponse(cells=cells)
        except PlanetsConsoleError as exc:
            raise HTTPException(
                status_code=getattr(exc, "http_error", 500),
                detail=str(exc),
            ) from exc

    result = with_timed_child(root, "get_warp_well_cells", "total", work)
    return finish_response(result, root)
