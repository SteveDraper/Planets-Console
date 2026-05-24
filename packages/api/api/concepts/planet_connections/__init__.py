"""Planet-to-planet travel reachability for one turn (warp, normal wells, optional flares)."""

from __future__ import annotations

from api.concepts.planet_connections.flare_pathfind import (
    _max_flare_arrival_extent,
    _reachable_via_flare_limited_depth,
    validate_illustrative_flare_route,
)
from api.concepts.planet_connections.routes import (
    ConnectionRoutesOutcome,
    connection_routes_for_planets,
    connection_routes_with_options,
)
from api.concepts.planet_connections.spatial_index import _PlanetSpatialIndex
from api.concepts.planet_connections.wells import (
    _pair_has_direct_connection,
    max_travel_distance,
)
from api.concepts.warp_well import min_distance_to_reachability_well
from api.transport.connections_options import FlareConnectionMode

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
    "min_distance_to_reachability_well",
    "validate_illustrative_flare_route",
]
