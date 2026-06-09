"""Scores military build inference BFF routes.

Included from the analytics router at prefix ``/scores`` so paths match
``/analytics/scores/inference/...`` (SPA: ``/bff/analytics/scores/inference/...``).
"""

from api.diagnostics import NOOP_DIAGNOSTICS, Diagnostics, timed_section
from api.transport.inference_stream import stream_inference_ndjson
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from bff.analytics import TurnScope, get_inference_response
from bff.core_client import get_core_client
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
)

router = APIRouter()


def _load_scores_row_inference(
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
    raise ValueError("scores inference loader does not support non-inference loads")


@router.get("/inference")
def get_scores_inference(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_id: int = Query(..., alias="playerId", ge=0),
    include: IncludeDiagnostics = False,
):
    """Per-row military score build inference for the Scores analytic."""
    bff_path = "/analytics/scores/inference"
    scope = TurnScope(game_id=game_id, perspective=perspective, turn=turn)

    root = optional_request_root(
        include,
        "GET",
        bff_path,
        gameId=game_id,
        turn=turn,
        perspective=perspective,
        playerId=player_id,
        handler="get_scores_inference",
    )
    inference_node = root.child("get_scores_inference")
    with timed_section(inference_node, "total"):
        body = get_inference_response(
            "scores",
            scope,
            _load_scores_row_inference,
            inference_node,
            player_id=player_id,
        )
    return finish_response(body, root)


@router.get(
    "/inference/table-stream",
    responses={
        200: {
            "description": "NDJSON stream of tagged inference events.",
            "content": {"application/x-ndjson": {}},
        }
    },
)
def get_scores_inference_table_stream(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_ids: str = Query(..., alias="playerIds"),
):
    """Stream build inference for all scoreboard rows on one NDJSON connection."""
    parsed_player_ids = tuple(int(part.strip()) for part in player_ids.split(",") if part.strip())
    core = get_core_client()
    return StreamingResponse(
        stream_inference_ndjson(
            lambda: core.iter_scores_table_inference_stream(
                game_id,
                perspective,
                turn,
                parsed_player_ids,
            )
        ),
        media_type="application/x-ndjson",
    )


@router.get("/inference/global-pause")
def get_scores_inference_global_pause(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
):
    """Whether scoreboard inference is globally paused for this turn scope."""
    return get_core_client().get_inference_global_pause_status(
        game_id,
        perspective,
        turn,
    )


@router.post("/inference/global-pause")
def post_scores_inference_global_pause(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
):
    """Pause all scoreboard inference jobs for this turn scope."""
    return get_core_client().pause_inference_globally(
        game_id,
        perspective,
        turn,
    )


@router.delete("/inference/global-pause")
def delete_scores_inference_global_pause(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
):
    """Resume globally paused scoreboard inference for this turn scope."""
    return get_core_client().resume_inference_globally(
        game_id,
        perspective,
        turn,
    )
