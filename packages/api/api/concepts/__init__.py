"""Pure game-domain rules (no HTTP, no storage).

Concept modules are imported by services and tests. Routers load state via services
then call into this package.
"""

from api.concepts.flare_points import (
    FLARE_POINT_TUPLES_GRAVITONIC_MOVEMENT,
    FLARE_POINT_TUPLES_REGULAR_MOVEMENT,
    FlareMovementKind,
    flare_points_for_warp,
)
from api.concepts.warp_well import (
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
    planet_is_in_debris_disk,
    warp_well_cartesian_distance,
)

__all__ = [
    "FLARE_POINT_TUPLES_GRAVITONIC_MOVEMENT",
    "FLARE_POINT_TUPLES_REGULAR_MOVEMENT",
    "FlareMovementKind",
    "WarpWellKind",
    "coordinate_in_warp_well",
    "flare_points_for_warp",
    "map_cell_indices_in_warp_well",
    "planet_is_in_debris_disk",
    "warp_well_cartesian_distance",
]
