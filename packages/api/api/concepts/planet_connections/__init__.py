"""Planet-to-planet travel reachability for one turn (warp, normal wells, optional flares).

Debris-disk planets use a simplified well: only the planet map cell counts as the well
(consistent with product guidance for this analytic).
"""

from __future__ import annotations

from api.concepts.planet_connections.flare_pathfind import (
    _max_flare_arrival_extent,
    _reachable_via_flare_limited_depth,
    validate_illustrative_flare_route,
)
from api.concepts.planet_connections.routes import (
    ConnectionRoutesOutcome,
    FlareConnectionMode,
    connection_routes_for_planets,
    connection_routes_with_options,
)
from api.concepts.planet_connections.spatial_index import _PlanetSpatialIndex
from api.concepts.planet_connections.wells import (
    _pair_has_direct_connection,
    max_travel_distance,
    min_distance_point_to_simplified_normal_well,
)

__all__ = [
    "ConnectionRoutesOutcome",
    "FlareConnectionMode",
    "_PlanetSpatialIndex",
    "_max_flare_arrival_extent",
    "_pair_has_direct_connection",
    "_reachable_via_flare_limited_depth",
    "connection_routes_for_planets",
    "connection_routes_with_options",
    "max_travel_distance",
    "min_distance_point_to_simplified_normal_well",
    "validate_illustrative_flare_route",
]
