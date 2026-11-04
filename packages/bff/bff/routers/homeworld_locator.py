"""BFF homeworld locator assertion and refresh routes (#37).

Included from the analytics router at prefix ``/homeworld-locator`` so paths match
``/analytics/homeworld-locator/assertions`` and ``.../refresh``.
"""

from api.transport.fleet_age_refetch import FleetAgeRefetchNoticeResponse
from api.transport.homeworld_assertions import HomeworldAssertionRequest
from fastapi import APIRouter, Query

from bff.core_client import get_core_client

router = APIRouter()


@router.post("/assertions")
def post_homeworld_locator_assertion(
    body: HomeworldAssertionRequest,
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    username: str = Query(""),
):
    """Upsert or revoke a homeworld location or ownership assertion."""
    return get_core_client().apply_homeworld_assertion(
        game_id,
        perspective,
        turn,
        axis=body.axis,
        action=body.action,
        planet_id=body.planet_id,
        sector_index=body.sector_index,
        owner_slot=body.owner_slot,
        username=username,
    )


@router.get("/fleet-age-refetch", response_model=FleetAgeRefetchNoticeResponse)
def get_homeworld_fleet_age_refetch(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    after_epoch: int = Query(0, alias="afterEpoch", ge=0),
) -> FleetAgeRefetchNoticeResponse:
    """Epoch of on-disk fleet build-turn identity changes since ``afterEpoch``.

    Does not ensure homeworld or fleet. The locator uses this to refetch a shown
    shell at or after ``fromTurn``.
    """
    body = get_core_client().fleet_age_refetch_notice(
        game_id,
        perspective,
        after_epoch=after_epoch,
    )
    return FleetAgeRefetchNoticeResponse.model_validate(body)


@router.post("/refresh")
def post_homeworld_locator_refresh(
    game_id: int = Query(..., alias="gameId"),
    turn: int = Query(..., ge=1),
    perspective: int = Query(..., ge=0),
    username: str = Query(""),
):
    """Wipe machine homeworld state and rebuild via ensure (asserts preserved)."""
    return get_core_client().refresh_homeworld_locator(
        game_id,
        perspective,
        turn,
        username=username,
    )
