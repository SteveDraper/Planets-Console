"""Analytics endpoints for the console shell."""

from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics, timed_section
from api.transport.connections_options import (
    DEFAULT_FLARE_DEPTH,
    DEFAULT_WARP_SPEED,
    FLARE_DEPTH_DESCRIPTION,
    FLARE_DEPTH_QUERY,
    FLARE_MODE_QUERY,
    GRAVITONIC_MOVEMENT_QUERY,
    INCLUDE_ILLUSTRATIVE_ROUTES_DESCRIPTION,
    INCLUDE_ILLUSTRATIVE_ROUTES_QUERY,
    WARP_SPEED_QUERY,
    FlareConnectionMode,
)
from api.transport.inference_hull_catalog import InferenceHullCatalogMaskUpdateRequest
from api.transport.inference_stream import stream_inference_row
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from bff.analytics import (
    ANALYTICS_LIST,
    ConnectionsMapQuery,
    TurnScope,
    get_inference_response,
    get_map_response,
    get_table_response,
    map_diagnostic_values,
    map_timing_section,
)
from bff.core_client import get_core_client
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)

router = APIRouter()


def _turn_analytics_from_core(
    game_id: int,
    perspective: int,
    turn_number: int,
    analytic_id: str,
    *,
    diagnostics: Diagnostics = NOOP_DIAGNOSTICS,
    **kwargs: object,
) -> dict:
    if kwargs.pop("inference_only", False):
        player_id = kwargs.pop("player_id", None)
        if not isinstance(player_id, int):
            raise ValueError("player_id is required for scores inference")
        if kwargs:
            raise ValueError(f"Unexpected kwargs for scores inference: {sorted(kwargs)}")
        return get_core_client().get_scores_row_inference(
            game_id,
            perspective,
            turn_number,
            player_id,
            diagnostics=diagnostics,
        )
    return get_core_client().get_turn_analytics(
        game_id,
        perspective,
        turn_number,
        analytic_id,
        diagnostics=diagnostics,
        **kwargs,
    )


@router.get("")
def list_analytics(
    include: IncludeDiagnostics = False,
):
    """Return analytics available to the console."""
    body = {"analytics": ANALYTICS_LIST}
    root = optional_request_root(include, "GET", "/analytics", handler="list_analytics")
    with_timed_child(root, "list_analytics", "total", lambda: body)
    return finish_response(body, root)


@router.get("/{analytic_id}/table")
def get_analytic_table(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    include_build_inference: bool = Query(False, alias="includeBuildInference"),
    include: IncludeDiagnostics = False,
):
    """Tabular data scoped to the selected game, turn, and perspective."""
    bff_path = f"/analytics/{analytic_id}/table"
    scope = TurnScope(game_id=game_id, perspective=perspective, turn=turn)

    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        includeBuildInference=include_build_inference,
        handler="get_analytic_table",
    )
    table_node = root.child("get_analytic_table")
    with timed_section(table_node, "total"):
        body = get_table_response(
            analytic_id,
            scope,
            _turn_analytics_from_core,
            table_node,
            include_build_inference=include_build_inference,
        )
    return finish_response(body, root)


@router.get("/{analytic_id}/inference")
def get_analytic_inference(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_id: int = Query(..., alias="playerId", ge=0),
    include: IncludeDiagnostics = False,
):
    """Per-row military score build inference for the Scores analytic."""
    bff_path = f"/analytics/{analytic_id}/inference"
    scope = TurnScope(game_id=game_id, perspective=perspective, turn=turn)

    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        playerId=player_id,
        handler="get_analytic_inference",
    )
    inference_node = root.child("get_analytic_inference")
    with timed_section(inference_node, "total"):
        body = get_inference_response(
            analytic_id,
            scope,
            _turn_analytics_from_core,
            inference_node,
            player_id=player_id,
        )
    return finish_response(body, root)


@router.get(
    "/{analytic_id}/inference/stream",
    responses={
        200: {
            "description": "NDJSON stream of solution, progress, complete, and error events.",
            "content": {
                "application/x-ndjson": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/InferenceStreamSolutionEvent"},
                            {"$ref": "#/components/schemas/InferenceStreamProgressEvent"},
                            {"$ref": "#/components/schemas/InferenceStreamCompleteEvent"},
                            {"$ref": "#/components/schemas/InferenceStreamErrorEvent"},
                        ]
                    }
                }
            },
        }
    },
)
def get_analytic_inference_stream(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_id: int = Query(..., alias="playerId", ge=0),
):
    """Stream per-row military score build inference for the Scores analytic (NDJSON)."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")

    core = get_core_client()
    return StreamingResponse(
        stream_inference_row(
            lambda: core.iter_scores_row_inference_stream(
                game_id,
                perspective,
                turn,
                player_id,
            )
        ),
        media_type="application/x-ndjson",
    )


@router.get(
    "/{analytic_id}/inference/table-stream",
    responses={
        200: {
            "description": "NDJSON stream of tagged inference events.",
            "content": {"application/x-ndjson": {}},
        }
    },
)
def get_analytic_inference_table_stream(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_ids: str = Query(..., alias="playerIds"),
):
    """Stream build inference for all scoreboard rows on one NDJSON connection."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")

    parsed_player_ids = tuple(int(part.strip()) for part in player_ids.split(",") if part.strip())
    core = get_core_client()
    return StreamingResponse(
        stream_inference_row(
            lambda: core.iter_scores_table_inference_stream(
                game_id,
                perspective,
                turn,
                parsed_player_ids,
            )
        ),
        media_type="application/x-ndjson",
    )


@router.post("/{analytic_id}/inference/stop")
def post_analytic_inference_stop(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_id: int = Query(..., alias="playerId", ge=0),
):
    """Halt build inference for one scoreboard row."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")
    return get_core_client().stop_scores_row_inference(
        game_id,
        perspective,
        turn,
        player_id,
    )


@router.get("/{analytic_id}/inference/hull-catalog")
def get_analytic_inference_hull_catalog(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_id: int = Query(..., alias="playerId", ge=0),
):
    """Master hull catalog and effective mask for one Scores inference row."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")
    return get_core_client().get_inference_hull_catalog_mask(
        game_id,
        perspective,
        turn,
        player_id,
    )


@router.put("/{analytic_id}/inference/hull-catalog")
def put_analytic_inference_hull_catalog(
    analytic_id: str,
    body: InferenceHullCatalogMaskUpdateRequest,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_id: int = Query(..., alias="playerId", ge=0),
):
    """Persist a user hull catalog mask override for one Scores inference row."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")
    return get_core_client().put_inference_hull_catalog_mask(
        game_id,
        perspective,
        turn,
        player_id,
        body.enabled_hull_ids,
    )


@router.delete("/{analytic_id}/inference/hull-catalog")
def delete_analytic_inference_hull_catalog(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_id: int = Query(..., alias="playerId", ge=0),
):
    """Clear a user hull catalog mask override for one Scores inference row."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")
    return get_core_client().reset_inference_hull_catalog_mask(
        game_id,
        perspective,
        turn,
        player_id,
    )


@router.get("/{analytic_id}/inference/global-pause")
def get_analytic_inference_global_pause(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
):
    """Whether scoreboard inference is globally paused for this turn scope."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")
    return get_core_client().get_inference_global_pause_status(
        game_id,
        perspective,
        turn,
    )


@router.post("/{analytic_id}/inference/global-pause")
def post_analytic_inference_global_pause(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
):
    """Pause all scoreboard inference jobs for this turn scope."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")
    return get_core_client().pause_inference_globally(
        game_id,
        perspective,
        turn,
    )


@router.delete("/{analytic_id}/inference/global-pause")
def delete_analytic_inference_global_pause(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
):
    """Resume globally paused scoreboard inference for this turn scope."""
    if analytic_id != "scores":
        from bff.errors import NotFoundError

        raise NotFoundError(f"Unknown analytic: {analytic_id}")
    return get_core_client().resume_inference_globally(
        game_id,
        perspective,
        turn,
    )


@router.get("/{analytic_id}/map")
def get_analytic_map(
    analytic_id: str,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    warp_speed: int = Query(DEFAULT_WARP_SPEED, ge=1, le=9, alias=WARP_SPEED_QUERY),
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
    include: IncludeDiagnostics = False,
):
    """Map data (nodes/edges). **base-map** returns planet nodes only (empty edges).

    **connections** returns route pairs for the SPA to draw as edges on those nodes.

    **stellar-cartography** returns overlay circles and wormhole graph geometry.

    Nodes use fixed Cartesian coordinates (x, y). The SPA fetches base-map first, then
    enabled map analytics, and merges layers (see docs/design-connections-analytic.md).
    """
    bff_path = f"/analytics/{analytic_id}/map"

    scope = TurnScope(game_id=game_id, perspective=perspective, turn=turn)
    query = ConnectionsMapQuery(
        warp_speed=warp_speed,
        gravitonic_movement=gravitonic_movement,
        flare_mode=flare_mode,
        flare_depth=flare_depth,
        include_illustrative_routes=include_illustrative_routes,
    )
    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        **map_diagnostic_values(analytic_id, query),
        handler="get_analytic_map",
    )
    map_node = root.child("get_analytic_map")
    with timed_section(map_node, map_timing_section(analytic_id)):
        body = get_map_response(
            analytic_id,
            scope,
            query,
            _turn_analytics_from_core,
            map_node,
        )
    return finish_response(body, root)
