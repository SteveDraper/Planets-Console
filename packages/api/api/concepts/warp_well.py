"""Warp well geometry in map coordinates (Euclidean / Cartesian distance on the map plane).

**Canonical geometry** (``coordinate_in_warp_well``, ``map_cell_indices_in_warp_well``):
point-in-well and cell enumeration for map overlay and concept HTTP routes. Debris-disk
planets have no well (empty cell list).

**Reachability geometry** (``point_in_reachability_well``, ``min_distance_to_reachability_well``):
fast helpers for Connections and pathfinding. Non-debris discs match canonical normal-well
rules; debris-disk planets use a point-only well at the planet map cell, which is
reachability-equivalent to having no extended well.
"""

import math
from enum import StrEnum

from api.models.planet import Planet

NORMAL_RADIUS = 3
HYPERJUMP_EXCLUSIVE_RADIUS = 3
NORMAL_WELL_CELL_COUNT = 29


class WarpWellKind(StrEnum):
    NORMAL = "normal"
    HYPERJUMP = "hyperjump"


def planet_is_in_debris_disk(planet: Planet) -> bool:
    """Non-zero ``debrisdisk`` means the planet has no warp wells for map/concept geometry."""
    return planet.debrisdisk != 0


def warp_well_cartesian_distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def coordinate_in_warp_well(
    planet: Planet,
    query_x: float,
    query_y: float,
    well_kind: WarpWellKind,
) -> bool:
    """Whether ``(query_x, query_y)`` lies in the given warp well around ``planet``."""
    if planet_is_in_debris_disk(planet):
        return False
    d = warp_well_cartesian_distance(float(planet.x), float(planet.y), query_x, query_y)
    if well_kind is WarpWellKind.NORMAL:
        return d <= NORMAL_RADIUS
    # HYPERJUMP
    return d < HYPERJUMP_EXCLUSIVE_RADIUS


def map_cell_indices_in_warp_well(planet: Planet, well_kind: WarpWellKind) -> list[tuple[int, int]]:
    """Map cell indices ``(gx, gy)`` whose center is inside the well (same rule as coordinate test).

    Cell center distance uses ``hypot(gx - planet.x, gy - planet.y)`` (equivalent to Euclidean
    distance between centers at half-integers).
    """
    if planet_is_in_debris_disk(planet):
        return []
    px, py = planet.x, planet.y
    out: list[tuple[int, int]] = []
    for dgx in range(-NORMAL_RADIUS, NORMAL_RADIUS + 1):
        for dgy in range(-NORMAL_RADIUS, NORMAL_RADIUS + 1):
            gx, gy = px + dgx, py + dgy
            d = warp_well_cartesian_distance(float(px), float(py), float(gx), float(gy))
            if well_kind is WarpWellKind.NORMAL:
                if d <= NORMAL_RADIUS:
                    out.append((gx, gy))
            else:
                if d < HYPERJUMP_EXCLUSIVE_RADIUS:
                    out.append((gx, gy))
    return sorted(out)


def min_distance_to_reachability_well(qx: float, qy: float, planet: Planet) -> float:
    """Minimum Euclidean distance from ``(qx, qy)`` to the planet's reachability well."""
    px, py = float(planet.x), float(planet.y)
    if planet_is_in_debris_disk(planet):
        return warp_well_cartesian_distance(px, py, qx, qy)
    return max(0.0, warp_well_cartesian_distance(px, py, qx, qy) - NORMAL_RADIUS)


def point_in_reachability_well(planet: Planet, qx: float, qy: float) -> bool:
    """Whether ``(qx, qy)`` lies in the planet's reachability well."""
    if planet_is_in_debris_disk(planet):
        return round(qx) == planet.x and round(qy) == planet.y
    return coordinate_in_warp_well(planet, qx, qy, WarpWellKind.NORMAL)
