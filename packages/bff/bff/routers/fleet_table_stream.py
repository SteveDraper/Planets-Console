"""Fleet table NDJSON stream BFF route."""

from api.transport.fleet_table_stream import stream_fleet_table_ndjson
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from bff.core_client import get_core_client

router = APIRouter()


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
