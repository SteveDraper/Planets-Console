"""Fleet table NDJSON stream and lightweight bootstrap BFF routes."""

from api.transport.fleet_table_stream import stream_fleet_table_ndjson
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from bff.analytics.fleet import ANALYTIC_ID, component_catalog_wire
from bff.core_client import get_core_client

router = APIRouter()


@router.get("/component-catalog")
def get_fleet_component_catalog(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
):
    """Host component display names for fleet table rendering without fleet compute."""
    turn_info = get_core_client().get_turn_info(game_id, perspective, turn)
    return {
        "analyticId": ANALYTIC_ID,
        "componentCatalog": component_catalog_wire(turn_info),
    }


@router.get(
    "/table-stream",
    responses={
        200: {
            "description": "NDJSON stream of tagged fleet table materialization events.",
            "content": {"application/x-ndjson": {}},
        }
    },
)
def get_fleet_table_stream(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    player_ids: str = Query(..., alias="playerIds"),
):
    """Stream fleet table materialization for requested players on one NDJSON connection."""
    parsed_player_ids = tuple(int(part.strip()) for part in player_ids.split(",") if part.strip())
    core = get_core_client()
    return StreamingResponse(
        stream_fleet_table_ndjson(
            lambda: core.iter_fleet_table_stream(
                game_id,
                perspective,
                turn,
                parsed_player_ids,
            )
        ),
        media_type="application/x-ndjson",
    )
