"""Global game concept routes (no game or turn scope)."""

from fastapi import APIRouter, Depends, Query

from api.concepts.flare_points import FlareMovementKind
from api.models.flare_point import FlarePoint
from api.services.flare_point_catalog_service import (
    FlarePointCatalogService,
    get_flare_point_catalog_service,
)
from api.transport.concept_flare_point import (
    FlareMovementTypeParam,
    FlarePointsListResponse,
    FlarePointWireModel,
    RelativeOffsetModel,
)

router = APIRouter(prefix="/v1/concepts", tags=["concepts"])


def _flare_point_to_wire(point: FlarePoint) -> FlarePointWireModel:
    wx, wy = point.waypoint_offset
    ax, ay = point.arrival_offset
    dx, dy = point.direct_aim_arrival_offset
    return FlarePointWireModel(
        waypoint_offset=RelativeOffsetModel(x=wx, y=wy),
        arrival_offset=RelativeOffsetModel(x=ax, y=ay),
        direct_aim_arrival_offset=RelativeOffsetModel(x=dx, y=dy),
    )


@router.get("/flare-points", response_model=FlarePointsListResponse)
def get_flare_points(
    warp_speed: int = Query(..., ge=1, le=9, description="Ship warp factor (1--9)."),
    movement_type: FlareMovementTypeParam = Query(
        ...,
        description="Whether the ship uses regular or gravitonic movement at this warp.",
    ),
    catalog: FlarePointCatalogService = Depends(get_flare_point_catalog_service),
) -> FlarePointsListResponse:
    """Return flare-point geometry for the given warp speed and movement type."""
    kind = FlareMovementKind(movement_type.value)
    points = catalog.list_flare_points_for_warp(warp_speed, kind)
    return FlarePointsListResponse(
        flare_points=[_flare_point_to_wire(p) for p in points],
    )
