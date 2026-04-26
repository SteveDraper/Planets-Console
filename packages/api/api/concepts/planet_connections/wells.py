"""Simplified well geometry and direct reachability in map cell coordinates."""

from __future__ import annotations

import math

from api.concepts.warp_well import (
    NORMAL_RADIUS,
    WarpWellKind,
    coordinate_in_warp_well,
    planet_is_in_debris_disk,
    warp_well_cartesian_distance,
)
from api.models.planet import Planet


def min_distance_point_to_simplified_normal_well(qx: float, qy: float, planet: Planet) -> float:
    """Minimum Euclidean distance from ``(qx, qy)`` to the other planet's simplified normal well."""
    px, py = float(planet.x), float(planet.y)
    if planet_is_in_debris_disk(planet):
        return warp_well_cartesian_distance(px, py, qx, qy)
    return max(0.0, warp_well_cartesian_distance(px, py, qx, qy) - NORMAL_RADIUS)


def point_in_simplified_normal_well(planet: Planet, qx: float, qy: float) -> bool:
    """Whether ``(qx, qy)`` lies in the simplified normal well (or planet cell for debris)."""
    if planet_is_in_debris_disk(planet):
        return round(qx) == planet.x and round(qy) == planet.y
    return coordinate_in_warp_well(planet, qx, qy, WarpWellKind.NORMAL)


def max_travel_distance(warp_speed: int, gravitonic_movement: bool) -> float:
    d = float(warp_speed * warp_speed)
    if gravitonic_movement:
        return d * 2.0
    return d


def _is_direct(from_planet: Planet, to_planet: Planet, max_travel: float) -> bool:
    ax, ay = float(from_planet.x), float(from_planet.y)
    return min_distance_point_to_simplified_normal_well(ax, ay, to_planet) <= max_travel + 1e-9


def _pair_has_direct_connection(planet_a: Planet, planet_b: Planet, max_travel: float) -> bool:
    """Undirected: a normal connection exists if either endpoint reaches the other's well."""
    return _is_direct(planet_a, planet_b, max_travel) or _is_direct(planet_b, planet_a, max_travel)


def _pair_reachable_in_k_normal_moves(
    planet_a: Planet, planet_b: Planet, max_travel: float, k: int
) -> bool:
    """True if, from one planet's map cell, the ship can reach the other's well in *k* or fewer
    **normal** moves, each of length at most *max_travel* (2D: union of *k* disks; same
    well-distance model as :func:`_is_direct`).

    Used to avoid labelling a pair as a depth-*k* **flare** route when no flare is required.
    """
    if k < 1 or not math.isfinite(max_travel) or max_travel <= 0.0:
        return False
    limit = k * max_travel + 1e-9
    d_from_a = min_distance_point_to_simplified_normal_well(
        float(planet_a.x), float(planet_a.y), planet_b
    )
    d_from_b = min_distance_point_to_simplified_normal_well(
        float(planet_b.x), float(planet_b.y), planet_a
    )
    return d_from_a <= limit or d_from_b <= limit
