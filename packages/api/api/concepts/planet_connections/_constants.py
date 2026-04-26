"""Module-level constants and caches for planet connection pathfinding."""

from __future__ import annotations

from api.concepts.warp_well import NORMAL_RADIUS
from api.models.flare_point import FlarePoint

MAX_GRID_CELL_VISITS = 12_000
_MAX_FLARE_CHAIN_DEPTH = 3
_MIN_EXTENT_FOR_CELL_SIZING = 1.0
# Extra headroom on the triangle-inequality distance prune (integer lattice + simplified
# well geometry). See :func:`.flare_pathfind._flare_path_state_exceeds_distance_bound`.
_FLARE_DISTANCE_BOUND_SLACK = float(NORMAL_RADIUS) + 1.0

# Per ``r = floor(max_travel)`` cache: offsets (dx,dy) in one open disk, ``ang = atan2(dy,dx)``
# in [0, 2π) sorted; enumeration walks from the angle nearest ``ref`` in circular zigzag.
_LATTICE_FULL_DISK_ANG: dict[int, list[tuple[int, int, float]]] = {}
_LATTICE_STRIDED_ANG: dict[int, list[tuple[int, int, float]]] = {}
# Flare table (tuple of FlarePoint): (Flare, atan2 on arrival, index in list) sorted by angle
# in [0, 2π); BFS order matches the integer lattice ring (bisect + circular zigzag).
_FLARES_ANGULAR_ROWS: dict[tuple[FlarePoint, ...], tuple[tuple[FlarePoint, float, int], ...]] = {}
