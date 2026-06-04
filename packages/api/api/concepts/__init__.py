"""Pure game-domain rules (no HTTP, no storage).

Concept modules are imported by services, analytics, and tests. Routers load state via
services then call into this package.

Race-specific ``raceid`` constants and mechanics live in ``races.py`` (see CONTEXT.md
**Race-specific game concept** and docs/design-analytics-structure.md).
"""

from api.concepts.flare_points import (
    FLARE_POINT_TUPLES_GRAVITONIC_MOVEMENT,
    FLARE_POINT_TUPLES_REGULAR_MOVEMENT,
    FlareMovementKind,
    flare_points_for_warp,
)
from api.concepts.races import (
    EVIL_EMPIRE_RACE_ID,
    evil_empire_free_starbase_fighters_per_host_turn,
    is_evil_empire,
)
from api.concepts.warp_well import (
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
    min_distance_to_reachability_well,
    planet_is_in_debris_disk,
    point_in_reachability_well,
    warp_well_cartesian_distance,
)

__all__ = [
    "EVIL_EMPIRE_RACE_ID",
    "FLARE_POINT_TUPLES_GRAVITONIC_MOVEMENT",
    "FLARE_POINT_TUPLES_REGULAR_MOVEMENT",
    "FlareMovementKind",
    "evil_empire_free_starbase_fighters_per_host_turn",
    "is_evil_empire",
    "WarpWellKind",
    "coordinate_in_warp_well",
    "flare_points_for_warp",
    "map_cell_indices_in_warp_well",
    "min_distance_to_reachability_well",
    "planet_is_in_debris_disk",
    "point_in_reachability_well",
    "warp_well_cartesian_distance",
]
