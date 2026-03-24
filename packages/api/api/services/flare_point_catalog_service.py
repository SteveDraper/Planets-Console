"""Static catalog lookups for game concepts that do not depend on stored game state."""

from api.concepts.flare_points import FlareMovementKind, flare_points_for_warp
from api.models.flare_point import FlarePoint


class FlarePointCatalogService:
    def list_flare_points_for_warp(
        self,
        warp_speed: int,
        movement_kind: FlareMovementKind,
    ) -> list[FlarePoint]:
        return flare_points_for_warp(warp_speed, movement_kind)


def get_flare_point_catalog_service() -> FlarePointCatalogService:
    return FlarePointCatalogService()
