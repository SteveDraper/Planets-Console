"""Planet-to-planet travel reachability for one turn (warp, normal wells, optional flares).

Debris-disk planets use a simplified well: only the planet map cell counts as the well
(consistent with product guidance for this analytic).
"""

from __future__ import annotations

import bisect
import math
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from api.concepts.flare_points import FlareMovementKind, flare_points_for_warp
from api.concepts.warp_well import (
    NORMAL_RADIUS,
    WarpWellKind,
    coordinate_in_warp_well,
    planet_is_in_debris_disk,
    warp_well_cartesian_distance,
)
from api.diagnostics import DiagnosticNode, timed_section
from api.models.flare_point import FlarePoint
from api.models.planet import Planet

MAX_GRID_CELL_VISITS = 12_000
_MAX_FLARE_CHAIN_DEPTH = 3
_MIN_EXTENT_FOR_CELL_SIZING = 1.0
# Extra headroom on the triangle-inequality distance prune so integer lattice + simplified
# well geometry do not over-prune (see _flare_path_state_exceeds_distance_bound).
_FLARE_DISTANCE_BOUND_SLACK = float(NORMAL_RADIUS) + 1.0

# Per ``r = floor(max_travel)`` cache: offsets (dx,dy) in one open disk, ``ang = atan2(dy,dx)``
# in [0, 2π) sorted; enumeration walks from the angle nearest ``ref`` in circular zigzag.
_LATTICE_FULL_DISK_ANG: dict[int, list[tuple[int, int, float]]] = {}
_LATTICE_STRIDED_ANG: dict[int, list[tuple[int, int, float]]] = {}
# Flare table (tuple of FlarePoint): (Flare, atan2 on arrival, index in list) sorted by angle
# in [0, 2π); BFS order matches the integer lattice ring (bisect + circular zigzag).
_FLARES_ANGULAR_ROWS: dict[tuple[FlarePoint, ...], tuple[tuple[FlarePoint, float, int], ...]] = (
    {}
)


class FlareConnectionMode(StrEnum):
    """How flare-assisted routes are combined with direct warp-well reachability."""

    OFF = "off"
    INCLUDE = "include"
    ONLY = "only"


class ConnectionRouteAlgorithm(StrEnum):
    """Which flare-candidate prefilter feeds :func:`connection_routes_with_options`."""

    DEFAULT = "default"
    """Legacy: single shared annulus from one ``scan_flare`` (historical default)."""

    PER_DEPTH_CENTER_ANNULUS = "perDepthCenterAnnulus"
    """Per-*k* center-distance ring ``(k*max_travel, k*hop_loose + NORMAL_RADIUS]`` unioned;
    this is the product default for :func:`connection_routes_with_options`. May miss valid
    pairs vs the legacy annulus in edge cases."""


@dataclass
class _FlareBfsMetrics:
    """Mutable counters for optional diagnostics (avoids per-pair child nodes in the BFS)."""

    bfs_runs: int = 0
    bfs_dequeues: int = 0
    bfs_enqueues: int = 0


@dataclass
class _FlareBfsHotspotTimings:
    """Cumulative wall-time (``perf_counter``) across BFS work for one eligibility layer.

    Sub-timers (``well_index`` / ``dest_well``) are included inside normal/flare loop totals.
    """

    distance_prune_sec: float = 0.0
    normal_branch_sec: float = 0.0
    flare_branch_sec: float = 0.0
    well_index_sec: float = 0.0
    dest_well_test_sec: float = 0.0

    def add_to_diagnostics(self, d: DiagnosticNode) -> None:
        d.values["bfsCumulativeHotspotDistancePruneSec"] = self.distance_prune_sec
        d.values["bfsCumulativeHotspotNormalBranchSec"] = self.normal_branch_sec
        d.values["bfsCumulativeHotspotFlareBranchSec"] = self.flare_branch_sec
        d.values["bfsCumulativeHotspotWellIndexSec"] = self.well_index_sec
        d.values["bfsCumulativeHotspotDestWellTestSec"] = self.dest_well_test_sec


@dataclass
class _LatticeBuildDiagnostics:
    """Records each **cache miss** in :func:`_get_lattice_angular_row` (build + store)."""

    builds: list[dict[str, int | float | bool]] = field(default_factory=list)

    def add_to_diagnostics(self, d: DiagnosticNode) -> None:
        d.values["latticeBuildEventCount"] = len(self.builds)
        d.values["latticeBuildCumulativeSec"] = (
            sum(float(b["buildSec"]) for b in self.builds) if self.builds else 0.0
        )
        d.values["latticeBuilds"] = list(self.builds)


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


@dataclass(frozen=True)
class _GridPoint:
    planet: Planet


class _PlanetSpatialIndex:
    """Uniform grid over map coordinates; same cell sizing idea as the frontend hover grid."""

    def __init__(self, planets: list[Planet]) -> None:
        self._points: list[_GridPoint] = []
        min_x = math.inf
        max_x = -math.inf
        min_y = math.inf
        max_y = -math.inf
        for p in planets:
            px, py = float(p.x), float(p.y)
            if not math.isfinite(px) or not math.isfinite(py):
                continue
            self._points.append(_GridPoint(planet=p))
            min_x = min(min_x, px)
            max_x = max(max_x, px)
            min_y = min(min_y, py)
            max_y = max(max_y, py)
        n = len(self._points)
        if n == 0:
            self._min_x = 0.0
            self._min_y = 0.0
            self._cell_size = 1.0
            self._buckets: dict[str, list[_GridPoint]] = {}
            return
        self._min_x = min_x
        self._min_y = min_y
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        area = span_x * span_y
        extent = max(span_x, span_y)
        extent_for_sizing = max(extent, _MIN_EXTENT_FOR_CELL_SIZING)
        from_area = math.sqrt(area / n)
        from_extent = extent_for_sizing / math.sqrt(n)
        self._cell_size = max(from_area, from_extent, 1e-6)
        self._buckets: dict[str, list[_GridPoint]] = {}
        for gp in self._points:
            p = gp.planet
            px, py = float(p.x), float(p.y)
            ix = int((px - self._min_x) // self._cell_size)
            iy = int((py - self._min_y) // self._cell_size)
            key = f"{ix},{iy}"
            self._buckets.setdefault(key, []).append(gp)

    def iter_planets_within_radius(
        self,
        center_x: float,
        center_y: float,
        radius: float,
        *,
        min_planet_id_exclusive: int | None = None,
    ) -> Iterator[Planet]:
        if not math.isfinite(center_x) or not math.isfinite(center_y) or not math.isfinite(radius):
            return
        r = max(radius, 0.0)
        r_sq = r * r
        if self._cell_size <= 0 or not self._buckets:
            yield from self._fallback_scan(center_x, center_y, r_sq, min_planet_id_exclusive)
            return

        ix_min = int((center_x - r - self._min_x) // self._cell_size)
        ix_max = int((center_x + r - self._min_x) // self._cell_size)
        iy_min = int((center_y - r - self._min_y) // self._cell_size)
        iy_max = int((center_y + r - self._min_y) // self._cell_size)
        nx = ix_max - ix_min + 1
        ny = iy_max - iy_min + 1
        if nx <= 0 or ny <= 0:
            return
        if nx * ny > MAX_GRID_CELL_VISITS:
            yield from self._fallback_scan(center_x, center_y, r_sq, min_planet_id_exclusive)
            return

        for ix in range(ix_min, ix_max + 1):
            for iy in range(iy_min, iy_max + 1):
                bucket = self._buckets.get(f"{ix},{iy}")
                if not bucket:
                    continue
                for gp in bucket:
                    p = gp.planet
                    if min_planet_id_exclusive is not None and p.id <= min_planet_id_exclusive:
                        continue
                    px, py = float(p.x), float(p.y)
                    dx = px - center_x
                    dy = py - center_y
                    if dx * dx + dy * dy <= r_sq:
                        yield p

    def _fallback_scan(
        self,
        center_x: float,
        center_y: float,
        r_sq: float,
        min_planet_id_exclusive: int | None,
    ) -> Iterator[Planet]:
        for gp in self._points:
            p = gp.planet
            if min_planet_id_exclusive is not None and p.id <= min_planet_id_exclusive:
                continue
            px, py = float(p.x), float(p.y)
            dx = px - center_x
            dy = py - center_y
            if dx * dx + dy * dy <= r_sq:
                yield p


def _max_flare_arrival_extent(flares: list[FlarePoint]) -> float:
    best = 0.0
    for f in flares:
        ax, ay = f.arrival_offset
        best = max(best, math.hypot(ax, ay))
    return best


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


def _point_lies_in_any_planet_well(
    qx: float,
    qy: float,
    well_index: _PlanetSpatialIndex,
    *,
    hotspot_time: _FlareBfsHotspotTimings | None = None,
) -> bool:
    """Whether ``(qx, qy)`` lies in any planet's simplified normal well (disc or debris cell).

    Only planets with centers within :data:`NORMAL_RADIUS` of the query are checked: a non-debris
    point in the well is always that close to the planet center; a debris well is a single map
    cell, so the center is still within ½ cell (well under ``NORMAL_RADIUS``) when the point lies
    in that cell.
    """
    t0 = time.perf_counter() if hotspot_time is not None else 0.0
    r = float(NORMAL_RADIUS)
    for p in well_index.iter_planets_within_radius(qx, qy, r):
        if point_in_simplified_normal_well(p, qx, qy):
            if hotspot_time is not None:
                hotspot_time.well_index_sec += time.perf_counter() - t0
            return True
    if hotspot_time is not None:
        hotspot_time.well_index_sec += time.perf_counter() - t0
    return False


def _abs_angle_diff_radians(a: float, b: float) -> float:
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return abs(d)


def _circular_radian_separation(a: float, b: float) -> float:
    """Shortest arc on the circle between two angles in radians (same as ``|a-b|`` mod 2π)."""
    d = a - b
    d = (d + math.pi) % (2 * math.pi) - math.pi
    return abs(d)


def _lattice_offset_ring_angular_sorted(
    r: int, r2: float, strided: bool
) -> list[tuple[int, int, float]]:
    """All ``(dx,dy,ang)`` with ``ang = atan2(dy,dx)`` in [0, 2π), sorted by ``ang``."""
    if strided:
        step = max(1, r // 10)
        sparse: set[tuple[int, int]] = set()
        for dx in range(-r, r + 1, step):
            for dy in range(-r, r + 1, step):
                if float(dx) * float(dx) + float(dy) * float(dy) > r2 + 1e-3:
                    continue
                if dx == 0 and dy == 0:
                    continue
                sparse.add((dx, dy))
        sub = max(1, step // 2)
        for ddx in (-r, 0, r):
            for ddy in range(-r, r + 1, sub):
                sparse.add((ddx, ddy))
        for ddy in (-r, 0, r):
            for ddx in range(-r, r + 1, sub):
                sparse.add((ddx, ddy))
        out = list(sparse)
    else:
        out = []
        for dx in range(-r, r + 1):
            dy_max = r * r - dx * dx
            if dy_max < 0:
                continue
            dy_max_i = int(math.sqrt(float(dy_max)) + 1e-9)
            for dy in range(-dy_max_i, dy_max_i + 1):
                if float(dx) * float(dx) + float(dy) * float(dy) > r2 + 1e-6:
                    continue
                if dx == 0 and dy == 0:
                    continue
                out.append((dx, dy))
    rows: list[tuple[int, int, float]] = []
    for dx, dy in out:
        ang = math.atan2(float(dy), float(dx))
        if ang < 0.0:
            ang += 2.0 * math.pi
        rows.append((dx, dy, ang))
    rows.sort(key=lambda t: (t[2], t[0], t[1]))
    return rows


def _get_lattice_angular_row(
    r: int,
    r2: float,
    strided: bool,
    *,
    lattice_diagnostics: _LatticeBuildDiagnostics | None = None,
) -> list[tuple[int, int, float]]:
    cache = _LATTICE_STRIDED_ANG if strided else _LATTICE_FULL_DISK_ANG
    if r not in cache:
        t0 = time.perf_counter()
        built = _lattice_offset_ring_angular_sorted(r, r2, strided=strided)
        cache[r] = built
        if lattice_diagnostics is not None:
            elapsed = time.perf_counter() - t0
            lattice_diagnostics.builds.append(
                {
                    "latticeRadiusR": r,
                    "strided": strided,
                    "buildSec": elapsed,
                    "offsetCount": len(built),
                }
            )
    return cache[r]


def _nearest_lattice_index_for_ref(angs: list[float], ref: float) -> int:
    """Index in ``angs`` (sorted) whose angle is circle-closest to ``ref``; O(log n) + O(1)."""
    n = len(angs)
    if n == 0:
        return 0
    r0 = ref % (2.0 * math.pi)
    i = bisect.bisect_left(angs, r0)
    cands: set[int] = {i % n, (i - 1) % n, 0, n - 1}
    return min(cands, key=lambda j: _circular_radian_separation(angs[j], r0))


def _iter_circular_index_zigzag(n: int, s: int) -> Iterator[int]:
    """All indices 0..n-1, starting at ``s``, expanding by ±1 on the ring each step."""
    if n == 0:
        return
    if n == 1:
        yield s
        return
    seen: set[int] = {s}
    yield s
    for k in range(1, n):
        for j in ((s + k) % n, (s - k) % n):
            if j in seen:
                continue
            seen.add(j)
            yield j
            if len(seen) >= n:
                return


def _get_flare_angular_rows(
    flares: list[FlarePoint],
) -> tuple[tuple[FlarePoint, float, int], ...]:
    """All flares, sorted by ``atan2(ay, ax)`` on ``arrival_offset``; table cached by identity."""
    key = tuple(flares)
    if key not in _FLARES_ANGULAR_ROWS:
        rows: list[tuple[FlarePoint, float, int]] = []
        for fi, f in enumerate(flares):
            ax, ay = f.arrival_offset[0], f.arrival_offset[1]
            ang = math.atan2(float(ay), float(ax))
            if ang < 0.0:
                ang += 2.0 * math.pi
            rows.append((f, ang, fi))
        rows.sort(
            key=lambda t: (t[1], t[0].arrival_offset[0], t[0].arrival_offset[1], t[2])
        )
        _FLARES_ANGULAR_ROWS[key] = tuple(rows)
    return _FLARES_ANGULAR_ROWS[key]


def _iter_flares_bfs_angular(
    flares: list[FlarePoint],
    px: int,
    py: int,
    *,
    to_planet: Planet,
) -> Iterator[tuple[FlarePoint, int]]:
    """``(FlarePoint, table_index)`` in circular order from the angle toward ``to_planet``."""
    rows = _get_flare_angular_rows(flares)
    n = len(rows)
    if n == 0:
        return
    angs: list[float] = [r[1] for r in rows]
    tx, ty = int(to_planet.x), int(to_planet.y)
    ref = math.atan2(float(ty - py), float(tx - px))
    sidx = _nearest_lattice_index_for_ref(angs, ref)
    for j in _iter_circular_index_zigzag(n, sidx):
        f, _a, fi = rows[j]
        yield f, fi


def _iter_normal_one_hop_integer_lattice(
    px: int,
    py: int,
    max_travel: float,
    *,
    to_planet: Planet,
    lattice_diagnostics: _LatticeBuildDiagnostics | None = None,
) -> Iterator[tuple[int, int, bool]]:
    """Integer map cells to consider for one **normal** move (2D, Euclidean
    at most ``max_travel``). Excludes the no-op offset (0, 0).

    Yields ``(nx, ny, in_lattice_ring)``. Greedy step first, then 8 disc-edge box
    corners, then the cached integer ``in_lattice_ring`` segment in **circular zigzag**
    from the angle closest to the toward-destination ray. On that ring only, remaining
    distance to the target well is **nearly** monotone in enumerate order; small integer
    **quantization** is a light sawtooth on that trend, and
    :data:`_FLARE_DISTANCE_BOUND_SLACK` in
    :func:`_flare_path_state_exceeds_distance_bound` absorbs it. For **distance
    pruning** with that bound, callers may ``break`` after the first pruned child **when**
    ``in_lattice_ring`` is true; greedy and box-corner candidates are not in that
    monotone order, so the same break must not apply there.

    Offsets in the one-hop disk (full for ``r <= 18``, strided otherwise) are **precomputed
    per** ``r`` and cached, sorted by ``atan2(dy, dx)`` in ``[0, 2\\pi)``. For each
    enumerate call, the cache is walked from the offset whose angle is **closest** to the
    toward-destination direction (``O(\\log n)`` ``bisect``) in **circular zigzag** (no
    per-BFS re-sort, no second pass over an unordered set).
    """
    if not math.isfinite(max_travel) or max_travel <= 0.0:
        return
    r2 = max_travel * max_travel
    r = int(min(math.floor(max_travel + 1e-9), 1_000_000))
    yielded: set[tuple[int, int]] = set()
    tx, ty = int(to_planet.x), int(to_planet.y)
    ref = math.atan2(float(ty - py), float(tx - px))

    def y_one(nx: int, ny: int) -> tuple[int, int] | None:
        if (nx, ny) == (px, py):
            return None
        ddx, ddy = float(nx - px), float(ny - py)
        if ddx * ddx + ddy * ddy > r2 + 1e-3:
            return None
        if (nx, ny) in yielded:
            return None
        yielded.add((nx, ny))
        return (nx, ny)

    def kind(dx: int, dy: int) -> float:
        if dx == 0 and dy == 0:
            return 0.0
        return _abs_angle_diff_radians(math.atan2(float(dy), float(dx)), ref)

    # 1) Greedy step toward the destination.
    vx, vy = float(tx - px), float(ty - py)
    dist = math.hypot(vx, vy)
    if dist > 1e-9:
        step = min(max_travel, dist)
        gx = int(round(px + (vx / dist) * step))
        gy = int(round(py + (vy / dist) * step))
        o = y_one(gx, gy)
        if o is not None:
            nx, ny = o
            yield nx, ny, False

    # 2) Disc-radius box corners, angular order from the toward-target ray.
    if r > 0:
        box_corners: list[tuple[int, int]] = [
            (r, 0),
            (-r, 0),
            (0, r),
            (0, -r),
            (r, r),
            (r, -r),
            (-r, r),
            (-r, -r),
        ]
        box_corners.sort(key=lambda t: (kind(t[0], t[1]), t[0], t[1]))
        for dx, dy in box_corners:
            o = y_one(px + dx, py + dy)
            if o is not None:
                nx, ny = o
                yield nx, ny, False

    strided = r > 18
    row = _get_lattice_angular_row(
        r, r2, strided=strided, lattice_diagnostics=lattice_diagnostics
    )
    if not row:
        return
    angs = [t[2] for t in row]
    sidx = _nearest_lattice_index_for_ref(angs, ref)
    for j in _iter_circular_index_zigzag(len(row), sidx):
        dx, dy, _ = row[j]
        o = y_one(px + dx, py + dy)
        if o is not None:
            nx, ny = o
            yield nx, ny, True


def _flare_path_state_exceeds_distance_bound(
    to_planet: Planet,
    max_hops: int,
    x: int,
    y: int,
    hops_completed: int,
    step_max: float,
    use_distance_prune: bool,
) -> bool:
    """Triangle-inequality bound: if True, this position is treated as too far to reach the goal
    in the remaining hop budget, so the state need not be expanded.

    A slack of :data:`NORMAL_RADIUS` (target simplified normal well radius) **+ 1** map unit is
    added to the movement budget (``rem * step_max``) so the prune stays conservative for
    integer grid positions and the simplified well distance model.

    ``hops_completed`` is the number of hops already taken to arrive at ``(x, y)`` (same as
    ``hops_used`` when dequeuing a BFS state, or the child's hop count after the incoming move).
    """
    if not use_distance_prune or step_max <= 0.0:
        return False
    rem = max_hops - hops_completed
    d_to_well = min_distance_point_to_simplified_normal_well(float(x), float(y), to_planet)
    return d_to_well > rem * step_max + _FLARE_DISTANCE_BOUND_SLACK


def _reachable_via_flare_limited_depth(
    from_planet: Planet,
    to_planet: Planet,
    flares: list[FlarePoint],
    max_depth: int,
    well_index: _PlanetSpatialIndex,
    max_travel: float,
    *,
    use_distance_prune: bool = True,
    bfs_metrics: _FlareBfsMetrics | None = None,
    hotspot_timings: _FlareBfsHotspotTimings | None = None,
    lattice_diagnostics: _LatticeBuildDiagnostics | None = None,
) -> bool:
    """True if, from ``from_planet``'s map cell, a route exists to ``to_planet``'s well using at
    most ``max_depth`` **hops**, each hop being **either** one normal move (Euclidean
    :math:`\\le` ``max_travel``) **or** one flare from the table, and using **at least one
    flare** in total.

    If a hop is the last allowed hop and the ship has not used a flare yet, that hop must be a
    flare (so a route with zero flares never counts, even if normal-only movement could reach
    the well on the last hop).

    Intermediate arrivals (after hops 1..N-1) must not lie in any planet's simplified well, same
    as the legacy flare-only BFS.

    Does not require hypot(waypoint) <= warp^2. Host allows longer waypoints; flare tables are
    authoritative for valid (waypoint, arrival) pairs at this warp.

    When ``use_distance_prune`` is set, the same triangle bound
    (``(remaining hops) * max(max_travel, hop_max)`` from :func:`_max_flare_arrival_extent`)
    is applied **before** each state's normal- and flare-neighbor enumeration, and for each
    generated child **first** (before any well or ``seen`` checks), so hopeless branches skip
    most work.

    **Normal one-hop set:** for ``floor(max_travel) > 18``, neighbor integers are a strided
    subset of the Euclidean disk (plus a greedy step toward the destination and box
    extremes), to keep BFS cost bounded. That can omit some valid mixed normal–flare routes
    in principle; the full open disk is used for smaller warps. Adjust
    :func:`_iter_normal_one_hop_integer_lattice` if stricter coverage is required.
    """
    if not flares or max_depth < 1:
        return False
    if not math.isfinite(max_travel) or max_travel <= 0.0:
        return False
    if bfs_metrics is not None:
        bfs_metrics.bfs_runs += 1
    hop_max = _max_flare_arrival_extent(flares) if use_distance_prune else 0.0
    step_max = max(max_travel, hop_max) if use_distance_prune else 0.0
    sx, sy = int(from_planet.x), int(from_planet.y)
    # (px, py, hops_used, used_flare)
    q: deque[tuple[int, int, int, bool]] = deque()
    q.append((sx, sy, 0, False))
    if bfs_metrics is not None:
        bfs_metrics.bfs_enqueues += 1
    seen: set[tuple[int, int, int, bool]] = {(sx, sy, 0, False)}

    def _in_destination_well(fx: float, fy: float) -> bool:
        if hotspot_timings is not None:
            t0 = time.perf_counter()
        out = point_in_simplified_normal_well(to_planet, fx, fy)
        if hotspot_timings is not None:
            hotspot_timings.dest_well_test_sec += time.perf_counter() - t0
        return out

    def _t_distance_prune(x: int, y: int, hops_completed: int) -> bool:
        if hotspot_timings is not None:
            t0 = time.perf_counter()
        out = _flare_path_state_exceeds_distance_bound(
            to_planet, max_depth, x, y, hops_completed, step_max, use_distance_prune
        )
        if hotspot_timings is not None:
            hotspot_timings.distance_prune_sec += time.perf_counter() - t0
        return out

    while q:
        px, py, hops_used, used_flare = q.popleft()
        if bfs_metrics is not None:
            bfs_metrics.bfs_dequeues += 1
        if hops_used >= max_depth:
            continue
        # Cheapest cull: drop doomed states before enumerating normal neighbors / all flares.
        if _t_distance_prune(px, py, hops_used):
            continue

        # Last hop, no flare used yet: may only use a flare (so the path includes ≥1 flare).
        last_hop_forces_flare = (hops_used == max_depth - 1) and (not used_flare)

        if not last_hop_forces_flare:
            if hotspot_timings is not None:
                t_nb = time.perf_counter()
            for nx, ny, in_lattice_ring in _iter_normal_one_hop_integer_lattice(
                px, py, max_travel, to_planet=to_planet, lattice_diagnostics=lattice_diagnostics
            ):
                nd = hops_used + 1
                if _t_distance_prune(nx, ny, nd):
                    if use_distance_prune and in_lattice_ring:
                        break
                    continue
                fnx, fny = float(nx), float(ny)
                if _in_destination_well(fnx, fny) and used_flare:
                    if hotspot_timings is not None:
                        hotspot_timings.normal_branch_sec += time.perf_counter() - t_nb
                    return True
                if _in_destination_well(fnx, fny) and not used_flare:
                    # In destination well but no flare yet: invalid flare-assisted path; do not
                    # enqueue (same as for flares: cannot stage inside dest without a flare used).
                    continue
                if nd >= max_depth:
                    continue
                if (nx, ny, nd, used_flare) in seen:
                    continue
                if _point_lies_in_any_planet_well(
                    fnx, fny, well_index, hotspot_time=hotspot_timings
                ):
                    continue
                seen.add((nx, ny, nd, used_flare))
                q.append((nx, ny, nd, used_flare))
                if bfs_metrics is not None:
                    bfs_metrics.bfs_enqueues += 1
            if hotspot_timings is not None:
                hotspot_timings.normal_branch_sec += time.perf_counter() - t_nb

        if hotspot_timings is not None:
            t_fb = time.perf_counter()
        for f, _fi in _iter_flares_bfs_angular(flares, px, py, to_planet=to_planet):
            ex = px + f.arrival_offset[0]
            ey = py + f.arrival_offset[1]
            nd = hops_used + 1
            if _t_distance_prune(ex, ey, nd):
                if use_distance_prune:
                    break
                continue
            fex, fey = float(ex), float(ey)
            new_used = True
            if _in_destination_well(fex, fey) and nd <= max_depth:
                if hotspot_timings is not None:
                    hotspot_timings.flare_branch_sec += time.perf_counter() - t_fb
                return True
            if nd < max_depth and (ex, ey, nd, new_used) not in seen:
                if _point_lies_in_any_planet_well(
                    fex, fey, well_index, hotspot_time=hotspot_timings
                ):
                    continue
                seen.add((ex, ey, nd, new_used))
                q.append((ex, ey, nd, new_used))
                if bfs_metrics is not None:
                    bfs_metrics.bfs_enqueues += 1
        if hotspot_timings is not None:
            hotspot_timings.flare_branch_sec += time.perf_counter() - t_fb
    return False


def _same_simplified_normal_well_type(planet_a: Planet, planet_b: Planet) -> bool:
    """True if both planets use the same simplified-well geometry (debris cell vs normal disc).

    When this holds, flare-assisted reachability at a given hop budget is symmetric: a path
    from A to B exists iff one from B to A exists, so only one BFS direction is needed.
    """
    return planet_is_in_debris_disk(planet_a) == planet_is_in_debris_disk(planet_b)


def _pair_reachable_via_flare_either_direction(
    planet_a: Planet,
    planet_b: Planet,
    flares: list[FlarePoint],
    max_hops: int,
    well_index: _PlanetSpatialIndex,
    max_travel: float,
    *,
    use_distance_prune: bool,
    bfs_metrics: _FlareBfsMetrics | None = None,
    hotspot_timings: _FlareBfsHotspotTimings | None = None,
    lattice_diagnostics: _LatticeBuildDiagnostics | None = None,
) -> bool:
    """Undirected flare test: ``planet_a`` first, then reverse only if well types differ."""
    ab = _reachable_via_flare_limited_depth(
        planet_a,
        planet_b,
        flares,
        max_hops,
        well_index,
        max_travel,
        use_distance_prune=use_distance_prune,
        bfs_metrics=bfs_metrics,
        hotspot_timings=hotspot_timings,
        lattice_diagnostics=lattice_diagnostics,
    )
    if ab or _same_simplified_normal_well_type(planet_a, planet_b):
        return ab
    return _reachable_via_flare_limited_depth(
        planet_b,
        planet_a,
        flares,
        max_hops,
        well_index,
        max_travel,
        use_distance_prune=use_distance_prune,
        bfs_metrics=bfs_metrics,
        hotspot_timings=hotspot_timings,
        lattice_diagnostics=lattice_diagnostics,
    )


def _canonical_pair_id(planet_a: Planet, planet_b: Planet) -> tuple[int, int]:
    """Lower planet id first for set keys (matches route ``from < to``)."""
    ia, ib = planet_a.id, planet_b.id
    if ia < ib:
        return (ia, ib)
    return (ib, ia)


def _iter_flare_candidate_edges(
    sorted_planets: list[Planet],
    index: _PlanetSpatialIndex,
    *,
    max_travel: float,
    scan_flare: float,
    scan_direct: float,
    use_flare_discs: bool,
) -> Iterator[tuple[Planet, Planet, bool]]:
    """Each ``(A, B, in_flare_inner_disc)`` for ``A.id < B.id``; inner disc = center distance ≤
    ``max_travel`` (flare BFS is never run in that annulus, only the direct check)."""
    for planet_a in sorted_planets:
        ax, ay = float(planet_a.x), float(planet_a.y)
        if use_flare_discs:
            inner_ids: set[int] = {
                p.id
                for p in index.iter_planets_within_radius(
                    ax, ay, max_travel, min_planet_id_exclusive=planet_a.id
                )
            }
            candidates_outer = list(
                index.iter_planets_within_radius(
                    ax, ay, scan_flare, min_planet_id_exclusive=planet_a.id
                )
            )
        else:
            inner_ids = set()
            candidates_outer = list(
                index.iter_planets_within_radius(
                    ax, ay, scan_direct, min_planet_id_exclusive=planet_a.id
                )
            )
        for planet_b in candidates_outer:
            if planet_b.id <= planet_a.id:
                continue
            in_flare_inner = use_flare_discs and (planet_b.id in inner_ids)
            yield planet_a, planet_b, in_flare_inner


def _list_flare_annulus_candidate_edges(
    sorted_planets: list[Planet],
    index: _PlanetSpatialIndex,
    *,
    max_travel: float,
    scan_flare: float,
    scan_direct: float,
) -> list[tuple[Planet, Planet]]:
    """Annulus candidate pairs (``use_flare_discs=True``), one spatial pass for reuse across *k*.

    Excludes inner-disc pairs so each layer reuses the same list without repeat index queries
    and per-``planet_a`` set/list allocations.
    """
    return [
        (pa, pb)
        for pa, pb, in_flare_inner in _iter_flare_candidate_edges(
            sorted_planets,
            index,
            max_travel=max_travel,
            scan_flare=scan_flare,
            scan_direct=scan_direct,
            use_flare_discs=True,
        )
        if not in_flare_inner
    ]


def _build_flare_eligible_by_layer(
    sorted_planets: list[Planet],
    index: _PlanetSpatialIndex,
    flares: list[FlarePoint],
    max_travel: float,
    scan_flare: float,
    scan_direct: float,
    max_k: int,
    *,
    use_distance_prune: bool = True,
    diagnostics: DiagnosticNode | None = None,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]], set[tuple[int, int]]]:
    """Compute disjoint contributions *e1*, *e2*, *e3* whose union matches the historical
    OR over *k* = 1..*max_k* of ``(not *k* normal moves) and BFS(*k*)``.

    Pass *k* adds pairs not in *e1|…|e{k-1}* that pass the *k* test, so deeper passes skip
    redundant BFS for pairs already satisfied at a shallower budget."""
    e1: set[tuple[int, int]] = set()
    e2: set[tuple[int, int]] = set()
    e3: set[tuple[int, int]] = set()

    annulus_edges = _list_flare_annulus_candidate_edges(
        sorted_planets,
        index,
        max_travel=max_travel,
        scan_flare=scan_flare,
        scan_direct=scan_direct,
    )
    annulus_n = len(annulus_edges)
    lattice_diagnostics = _LatticeBuildDiagnostics() if diagnostics is not None else None
    if diagnostics is not None:
        # Pairs with center distance ≤ max_travel use direct check only; annulus BFS uses
        # max_travel < d ≤ scan_flare (see _iter_flare_candidate_edges).
        diagnostics.values["annulusInnerRadius"] = max_travel
        diagnostics.values["annulusOuterRadius"] = scan_flare
        diagnostics.values["scanDirect"] = scan_direct

    m1 = _FlareBfsMetrics() if diagnostics is not None else None
    hot1 = _FlareBfsHotspotTimings() if diagnostics is not None else None
    if diagnostics is not None:
        d1 = diagnostics.child("flare_transitive_k1")
        d1.values["k"] = 1
        with timed_section(d1, "total"):
            for planet_a, planet_b in annulus_edges:
                key = _canonical_pair_id(planet_a, planet_b)
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 1
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    1,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m1,
                    hotspot_timings=hot1,
                    lattice_diagnostics=lattice_diagnostics,
                ):
                    e1.add(key)
        d1.values["annulusPairs"] = annulus_n
        d1.values["pairsTestedInLayer"] = annulus_n
        d1.values["connectionsFoundInLayer"] = len(e1)
        d1.values["cumulativeConnections"] = len(e1)
        if m1 is not None:
            d1.values["bfsRuns"] = m1.bfs_runs
            d1.values["intermediateRoutePoints"] = m1.bfs_dequeues
            d1.values["searchEnqueues"] = m1.bfs_enqueues
        if hot1 is not None:
            hot1.add_to_diagnostics(d1)
    else:
        for planet_a, planet_b in annulus_edges:
            key = _canonical_pair_id(planet_a, planet_b)
            if not _pair_reachable_in_k_normal_moves(
                planet_a, planet_b, max_travel, 1
            ) and _pair_reachable_via_flare_either_direction(
                planet_a,
                planet_b,
                flares,
                1,
                index,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e1.add(key)

    if max_k < 2:
        if diagnostics is not None and lattice_diagnostics is not None:
            lattice_diagnostics.add_to_diagnostics(diagnostics)
        return (e1, e2, e3)

    m2 = _FlareBfsMetrics() if diagnostics is not None else None
    hot2 = _FlareBfsHotspotTimings() if diagnostics is not None else None
    if diagnostics is not None:
        d2 = diagnostics.child("flare_transitive_k2")
        d2.values["k"] = 2
        with timed_section(d2, "total"):
            n_past_s1 = 0
            for planet_a, planet_b in annulus_edges:
                key = _canonical_pair_id(planet_a, planet_b)
                if key in e1:
                    continue
                n_past_s1 += 1
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 2
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    2,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m2,
                    hotspot_timings=hot2,
                    lattice_diagnostics=lattice_diagnostics,
                ):
                    e2.add(key)
        d2.values["annulusPairs"] = annulus_n
        d2.values["pairsTestedInLayer"] = annulus_n
        d2.values["pairCandidatesPastShallowerLayers"] = n_past_s1
        d2.values["connectionsFoundInLayer"] = len(e2)
        d2.values["cumulativeConnections"] = len(e1) + len(e2)
        if m2 is not None:
            d2.values["bfsRuns"] = m2.bfs_runs
            d2.values["intermediateRoutePoints"] = m2.bfs_dequeues
            d2.values["searchEnqueues"] = m2.bfs_enqueues
        if hot2 is not None:
            hot2.add_to_diagnostics(d2)
    else:
        for planet_a, planet_b in annulus_edges:
            key = _canonical_pair_id(planet_a, planet_b)
            if key in e1:
                continue
            if not _pair_reachable_in_k_normal_moves(
                planet_a, planet_b, max_travel, 2
            ) and _pair_reachable_via_flare_either_direction(
                planet_a,
                planet_b,
                flares,
                2,
                index,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e2.add(key)

    if max_k < 3:
        if diagnostics is not None and lattice_diagnostics is not None:
            lattice_diagnostics.add_to_diagnostics(diagnostics)
        return (e1, e2, e3)
    e12 = e1 | e2

    m3 = _FlareBfsMetrics() if diagnostics is not None else None
    hot3 = _FlareBfsHotspotTimings() if diagnostics is not None else None
    if diagnostics is not None:
        d3 = diagnostics.child("flare_transitive_k3")
        d3.values["k"] = 3
        with timed_section(d3, "total"):
            n_past_s12 = 0
            for planet_a, planet_b in annulus_edges:
                key = _canonical_pair_id(planet_a, planet_b)
                if key in e12:
                    continue
                n_past_s12 += 1
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 3
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    3,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m3,
                    hotspot_timings=hot3,
                    lattice_diagnostics=lattice_diagnostics,
                ):
                    e3.add(key)
        d3.values["annulusPairs"] = annulus_n
        d3.values["pairsTestedInLayer"] = annulus_n
        d3.values["pairCandidatesPastShallowerLayers"] = n_past_s12
        d3.values["connectionsFoundInLayer"] = len(e3)
        d3.values["cumulativeConnections"] = len(e1) + len(e2) + len(e3)
        if m3 is not None:
            d3.values["bfsRuns"] = m3.bfs_runs
            d3.values["intermediateRoutePoints"] = m3.bfs_dequeues
            d3.values["searchEnqueues"] = m3.bfs_enqueues
        if hot3 is not None:
            hot3.add_to_diagnostics(d3)
    else:
        for planet_a, planet_b in annulus_edges:
            key = _canonical_pair_id(planet_a, planet_b)
            if key in e12:
                continue
            if not _pair_reachable_in_k_normal_moves(
                planet_a, planet_b, max_travel, 3
            ) and _pair_reachable_via_flare_either_direction(
                planet_a,
                planet_b,
                flares,
                3,
                index,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e3.add(key)
    if diagnostics is not None and lattice_diagnostics is not None:
        lattice_diagnostics.add_to_diagnostics(diagnostics)
    return (e1, e2, e3)


_State4 = tuple[int, int, int, bool]


def _reconstruct_flare_bfs_path(
    parent: dict[_State4, tuple[_State4, str, tuple]],
    goal: _State4,
    start: _State4,
    flares: list[FlarePoint],
) -> list[dict[str, bool | int | list[int]]]:
    steps: list[dict[str, bool | int | list[int]]] = []
    s: _State4 | None = goal
    while s != start:
        if s not in parent:
            return []
        prev, code, data = parent[s]
        if code == "n":
            nx, ny = int(data[0]), int(data[1])
            steps.append({"kind": "normal", "to": {"x": nx, "y": ny}})
        else:
            fi, ex, ey = int(data[0]), int(data[1]), int(data[2])
            f = flares[fi]
            steps.append(
                {
                    "kind": "flare",
                    "to": {"x": ex, "y": ey},
                    "waypointOffset": [f.waypoint_offset[0], f.waypoint_offset[1]],
                    "arrivalOffset": [f.arrival_offset[0], f.arrival_offset[1]],
                }
            )
        s = prev
    steps.reverse()
    return steps


def _reachable_flare_bfs_path(
    from_planet: Planet,
    to_planet: Planet,
    flares: list[FlarePoint],
    max_depth: int,
    well_index: _PlanetSpatialIndex,
    max_travel: float,
    *,
    use_distance_prune: bool,
) -> list[dict[str, bool | int | list[int]]] | None:
    """First valid ≥1-flare path; same rules as ``_reachable_via_flare_limited_depth``."""
    if not flares or max_depth < 1 or not math.isfinite(max_travel) or max_travel <= 0.0:
        return None
    hop_max = _max_flare_arrival_extent(flares) if use_distance_prune else 0.0
    step_max = max(max_travel, hop_max) if use_distance_prune else 0.0
    sx, sy = int(from_planet.x), int(from_planet.y)
    start: _State4 = (sx, sy, 0, False)
    q: deque[_State4] = deque()
    q.append(start)
    parent: dict[_State4, tuple[_State4, str, tuple]] = {}
    seen: set[_State4] = {start}
    while q:
        px, py, hops_used, used_flare = q.popleft()
        if hops_used >= max_depth:
            continue
        if _flare_path_state_exceeds_distance_bound(
            to_planet, max_depth, px, py, hops_used, step_max, use_distance_prune
        ):
            continue
        last_hop_forces_flare = (hops_used == max_depth - 1) and (not used_flare)
        cur: _State4 = (px, py, hops_used, used_flare)
        if not last_hop_forces_flare:
            for nx, ny, in_lattice_ring in _iter_normal_one_hop_integer_lattice(
                px, py, max_travel, to_planet=to_planet
            ):
                nd = hops_used + 1
                if _flare_path_state_exceeds_distance_bound(
                    to_planet, max_depth, nx, ny, nd, step_max, use_distance_prune
                ):
                    if use_distance_prune and in_lattice_ring:
                        break
                    continue
                fnx, fny = float(nx), float(ny)
                nxt: _State4 = (nx, ny, nd, used_flare)
                if point_in_simplified_normal_well(to_planet, fnx, fny) and used_flare:
                    parent[nxt] = (cur, "n", (nx, ny))
                    return _reconstruct_flare_bfs_path(parent, nxt, start, flares)
                if point_in_simplified_normal_well(to_planet, fnx, fny) and not used_flare:
                    continue
                if nd >= max_depth:
                    continue
                if nxt in seen:
                    continue
                if _point_lies_in_any_planet_well(fnx, fny, well_index):
                    continue
                parent[nxt] = (cur, "n", (nx, ny))
                seen.add(nxt)
                q.append(nxt)
        for f, fi in _iter_flares_bfs_angular(flares, px, py, to_planet=to_planet):
            ex = px + f.arrival_offset[0]
            ey = py + f.arrival_offset[1]
            nd = hops_used + 1
            if _flare_path_state_exceeds_distance_bound(
                to_planet, max_depth, ex, ey, nd, step_max, use_distance_prune
            ):
                if use_distance_prune:
                    break
                continue
            fex, fey = float(ex), float(ey)
            nxtf: _State4 = (ex, ey, nd, True)
            if point_in_simplified_normal_well(to_planet, fex, fey) and nd <= max_depth:
                parent[nxtf] = (cur, "f", (fi, ex, ey))
                return _reconstruct_flare_bfs_path(parent, nxtf, start, flares)
            if nd < max_depth and nxtf not in seen:
                if _point_lies_in_any_planet_well(fex, fey, well_index):
                    continue
                parent[nxtf] = (cur, "f", (fi, ex, ey))
                seen.add(nxtf)
                q.append(nxtf)
    return None


def _pair_flare_path_either_direction(
    planet_a: Planet,
    planet_b: Planet,
    flares: list[FlarePoint],
    max_hops: int,
    well_index: _PlanetSpatialIndex,
    max_travel: float,
    *,
    use_distance_prune: bool,
) -> list[dict[str, bool | int | list[int]]] | None:
    p = _reachable_flare_bfs_path(
        planet_a,
        planet_b,
        flares,
        max_hops,
        well_index,
        max_travel,
        use_distance_prune=use_distance_prune,
    )
    if p is not None:
        return p
    if _same_simplified_normal_well_type(planet_a, planet_b):
        return None
    return _reachable_flare_bfs_path(
        planet_b,
        planet_a,
        flares,
        max_hops,
        well_index,
        max_travel,
        use_distance_prune=use_distance_prune,
    )


def _greedy_normal_reaches_in_hops(
    from_planet: Planet,
    to_planet: Planet,
    num_hops: int,
    max_travel: float,
) -> bool:
    """Each hop: among legal one-hop normal cells, pick one minimizing distance to ``to``'s well."""
    if num_hops < 1:
        return False
    px, py = int(from_planet.x), int(from_planet.y)
    for _ in range(num_hops):
        best: tuple[int, int] | None = None
        best_d = math.inf
        for nx, ny, _ in _iter_normal_one_hop_integer_lattice(
            px, py, max_travel, to_planet=to_planet
        ):
            d = min_distance_point_to_simplified_normal_well(float(nx), float(ny), to_planet)
            if best is None or d < best_d - 1e-12 or (abs(d - best_d) <= 1e-12 and (nx, ny) < best):
                best_d = d
                best = (nx, ny)
        if best is None:
            return False
        px, py = best
    return point_in_simplified_normal_well(to_planet, float(px), float(py))


def validate_illustrative_flare_route(
    from_planet: Planet,
    to_planet: Planet,
    path: list[dict[str, bool | int | list[int]]] | None,
    max_travel: float,
) -> str | None:
    """Return an error string if invalid; None if checks pass."""
    if not path:
        return "empty path"
    has_flare = any(s.get("kind") == "flare" for s in path)
    if not has_flare:
        return "path has no flare hop"
    h = len(path)
    if _greedy_normal_reaches_in_hops(from_planet, to_planet, h, max_travel):
        return (
            "greedy normal-only path reaches destination in "
            f"{h} hop(s), same length as illustrated path"
        )
    return None


def _per_depth_center_annulus_radii(
    k: int, max_travel: float, hop_loose: float
) -> tuple[float, float]:
    """Center-distance annulus (exclusive inner, inclusive outer) for per-depth *k*."""
    inner = k * max_travel
    outer = k * hop_loose + float(NORMAL_RADIUS)
    return (inner, outer)


def _list_per_depth_center_annulus_for_k(
    sorted_planets: list[Planet],
    *,
    k: int,
    max_travel: float,
    hop_loose: float,
) -> list[tuple[Planet, Planet]]:
    inner, outer = _per_depth_center_annulus_radii(k, max_travel, hop_loose)
    if outer <= inner + 1e-12:
        return []
    out: list[tuple[Planet, Planet]] = []
    for i, pa in enumerate(sorted_planets):
        ax, ay = float(pa.x), float(pa.y)
        for pb in sorted_planets[i + 1 :]:
            bx, by = float(pb.x), float(pb.y)
            d = math.hypot(bx - ax, by - ay)
            if inner < d <= outer + 1e-9:
                out.append((pa, pb))
    return out


def _build_flare_eligible_per_depth_center_annuli(
    sorted_planets: list[Planet],
    index: _PlanetSpatialIndex,
    flares: list[FlarePoint],
    max_travel: float,
    hop_loose: float,
    max_k: int,
    *,
    use_distance_prune: bool,
    diagnostics: DiagnosticNode | None = None,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]], set[tuple[int, int]]]:
    e1: set[tuple[int, int]] = set()
    e2: set[tuple[int, int]] = set()
    e3: set[tuple[int, int]] = set()
    lattice_diagnostics = _LatticeBuildDiagnostics() if diagnostics is not None else None
    m1 = _FlareBfsMetrics() if diagnostics is not None else None
    m2 = _FlareBfsMetrics() if diagnostics is not None else None
    m3 = _FlareBfsMetrics() if diagnostics is not None else None
    hot1 = _FlareBfsHotspotTimings() if diagnostics is not None else None
    hot2 = _FlareBfsHotspotTimings() if diagnostics is not None else None
    hot3 = _FlareBfsHotspotTimings() if diagnostics is not None else None
    if diagnostics is not None:
        diagnostics.values["maxTravel"] = max_travel
        diagnostics.values["hopLoose"] = hop_loose
        diagnostics.values["normalRadius"] = float(NORMAL_RADIUS)
        for kk in range(1, max_k + 1):
            inn, outv = _per_depth_center_annulus_radii(kk, max_travel, hop_loose)
            diagnostics.values[f"annulusK{kk}Inner"] = inn
            diagnostics.values[f"annulusK{kk}Outer"] = outv
    if max_k >= 1:
        ann1 = _list_per_depth_center_annulus_for_k(
            sorted_planets, k=1, max_travel=max_travel, hop_loose=hop_loose
        )
        inner1, outer1 = _per_depth_center_annulus_radii(1, max_travel, hop_loose)
        if diagnostics is not None:
            d1 = diagnostics.child("flare_per_depth_center_k1")
            d1.values["k"] = 1
            d1.values["annulusInnerRadius"] = inner1
            d1.values["annulusOuterRadius"] = outer1
            d1.values["annulusPairs"] = len(ann1)
        if diagnostics is not None and d1 is not None and m1 is not None:
            with timed_section(d1, "total"):
                for planet_a, planet_b in ann1:
                    key = _canonical_pair_id(planet_a, planet_b)
                    if not _pair_reachable_in_k_normal_moves(
                        planet_a, planet_b, max_travel, 1
                    ) and _pair_reachable_via_flare_either_direction(
                        planet_a,
                        planet_b,
                        flares,
                        1,
                        index,
                        max_travel,
                        use_distance_prune=use_distance_prune,
                        bfs_metrics=m1,
                        hotspot_timings=hot1,
                        lattice_diagnostics=lattice_diagnostics,
                    ):
                        e1.add(key)
            d1.values["pairsTestedInLayer"] = len(ann1)
            d1.values["connectionsFoundInLayer"] = len(e1)
            d1.values["cumulativeConnections"] = len(e1)
            d1.values["bfsRuns"] = m1.bfs_runs
            d1.values["intermediateRoutePoints"] = m1.bfs_dequeues
            d1.values["searchEnqueues"] = m1.bfs_enqueues
            if hot1 is not None:
                hot1.add_to_diagnostics(d1)
        else:
            for planet_a, planet_b in ann1:
                key = _canonical_pair_id(planet_a, planet_b)
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 1
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    1,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=None,
                ):
                    e1.add(key)
    if max_k < 2:
        if diagnostics is not None and lattice_diagnostics is not None:
            lattice_diagnostics.add_to_diagnostics(diagnostics)
        return (e1, e2, e3)
    if max_k >= 2:
        ann2 = _list_per_depth_center_annulus_for_k(
            sorted_planets, k=2, max_travel=max_travel, hop_loose=hop_loose
        )
        inner2, outer2 = _per_depth_center_annulus_radii(2, max_travel, hop_loose)
        if diagnostics is not None:
            d2 = diagnostics.child("flare_per_depth_center_k2")
            d2.values["k"] = 2
            d2.values["annulusInnerRadius"] = inner2
            d2.values["annulusOuterRadius"] = outer2
            d2.values["annulusPairs"] = len(ann2)
        if diagnostics is not None and d2 is not None and m2 is not None:
            with timed_section(d2, "total"):
                n_past_s1 = 0
                for planet_a, planet_b in ann2:
                    key = _canonical_pair_id(planet_a, planet_b)
                    if key in e1:
                        continue
                    n_past_s1 += 1
                    if not _pair_reachable_in_k_normal_moves(
                        planet_a, planet_b, max_travel, 2
                    ) and _pair_reachable_via_flare_either_direction(
                        planet_a,
                        planet_b,
                        flares,
                        2,
                        index,
                        max_travel,
                        use_distance_prune=use_distance_prune,
                        bfs_metrics=m2,
                        hotspot_timings=hot2,
                        lattice_diagnostics=lattice_diagnostics,
                    ):
                        e2.add(key)
            d2.values["pairsTestedInLayer"] = len(ann2)
            d2.values["pairCandidatesPastShallowerLayers"] = n_past_s1
            d2.values["connectionsFoundInLayer"] = len(e2)
            d2.values["cumulativeConnections"] = len(e1) + len(e2)
            d2.values["bfsRuns"] = m2.bfs_runs
            d2.values["intermediateRoutePoints"] = m2.bfs_dequeues
            d2.values["searchEnqueues"] = m2.bfs_enqueues
            if hot2 is not None:
                hot2.add_to_diagnostics(d2)
        else:
            for planet_a, planet_b in ann2:
                key = _canonical_pair_id(planet_a, planet_b)
                if key in e1:
                    continue
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 2
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    2,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=None,
                ):
                    e2.add(key)
    if max_k < 3:
        if diagnostics is not None and lattice_diagnostics is not None:
            lattice_diagnostics.add_to_diagnostics(diagnostics)
        return (e1, e2, e3)
    ann3 = _list_per_depth_center_annulus_for_k(
        sorted_planets, k=3, max_travel=max_travel, hop_loose=hop_loose
    )
    inner3, outer3 = _per_depth_center_annulus_radii(3, max_travel, hop_loose)
    e12 = e1 | e2
    if diagnostics is not None:
        d3 = diagnostics.child("flare_per_depth_center_k3")
        d3.values["k"] = 3
        d3.values["annulusInnerRadius"] = inner3
        d3.values["annulusOuterRadius"] = outer3
        d3.values["annulusPairs"] = len(ann3)
    if diagnostics is not None and d3 is not None and m3 is not None:
        with timed_section(d3, "total"):
            n_past_s12 = 0
            for planet_a, planet_b in ann3:
                key = _canonical_pair_id(planet_a, planet_b)
                if key in e12:
                    continue
                n_past_s12 += 1
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 3
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    3,
                    index,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m3,
                    hotspot_timings=hot3,
                    lattice_diagnostics=lattice_diagnostics,
                ):
                    e3.add(key)
        d3.values["pairsTestedInLayer"] = len(ann3)
        d3.values["pairCandidatesPastShallowerLayers"] = n_past_s12
        d3.values["connectionsFoundInLayer"] = len(e3)
        d3.values["cumulativeConnections"] = len(e1) + len(e2) + len(e3)
        d3.values["bfsRuns"] = m3.bfs_runs
        d3.values["intermediateRoutePoints"] = m3.bfs_dequeues
        d3.values["searchEnqueues"] = m3.bfs_enqueues
        if hot3 is not None:
            hot3.add_to_diagnostics(d3)
    else:
        for planet_a, planet_b in ann3:
            key = _canonical_pair_id(planet_a, planet_b)
            if key in e12:
                continue
            if not _pair_reachable_in_k_normal_moves(
                planet_a, planet_b, max_travel, 3
            ) and _pair_reachable_via_flare_either_direction(
                planet_a,
                planet_b,
                flares,
                3,
                index,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e3.add(key)
    if diagnostics is not None and lattice_diagnostics is not None:
        lattice_diagnostics.add_to_diagnostics(diagnostics)
    return (e1, e2, e3)


@dataclass
class ConnectionRoutesOutcome:
    """Result of :func:`connection_routes_with_options` (routes plus optional test comparison)."""

    routes: list[dict[str, bool | int | list | str | dict]]
    connection_route_test: dict[str, bool | int | float | str | list | dict] | None = None


def _enrich_connection_route_comparison_diff(test: dict[str, object]) -> None:
    """Mutates *test* (A/B output) with ``diff``: flare edge set deltas, full edge sig diff, and
    validation failure copies for both algorithms."""
    d_routes = test["default"]["routes"]
    p_routes = test["perDepthCenterAnnulus"]["routes"]
    v_def = test["default"]["illustrativeValidationErrors"]
    v_per = test["perDepthCenterAnnulus"]["illustrativeValidationErrors"]

    def _flare_edge_pairs(
        rs: list[dict[str, object]],
    ) -> set[tuple[int, int]]:
        return {
            (int(x["fromPlanetId"]), int(x["toPlanetId"])) for x in rs if x.get("viaFlare") is True
        }

    def _edge_sig(
        rs: list[dict[str, object]],
    ) -> set[tuple[int, int, bool]]:
        return {(int(x["fromPlanetId"]), int(x["toPlanetId"]), bool(x.get("viaFlare"))) for x in rs}

    fd, fp_ = _flare_edge_pairs(d_routes), _flare_edge_pairs(p_routes)
    sd, sp_ = _edge_sig(d_routes), _edge_sig(p_routes)
    only_d = fd - fp_
    only_p = fp_ - fd
    test["diff"] = {
        "flareEdgesOnlyInDefault": [
            {"fromPlanetId": a, "toPlanetId": b} for a, b in sorted(only_d)
        ],
        "flareEdgesOnlyInPerDepthCenterAnnulus": [
            {"fromPlanetId": a, "toPlanetId": b} for a, b in sorted(only_p)
        ],
        "edgeSignatureSymmetricDifference": [
            {
                "fromPlanetId": a,
                "toPlanetId": b,
                "viaFlare": vf,
            }
            for a, b, vf in sorted(sd.symmetric_difference(sp_))
        ],
        "validationFailuresDefault": list(v_def),
        "validationFailuresPerDepthCenterAnnulus": list(v_per),
    }


def connection_routes_with_options(
    planets: list[Planet],
    *,
    warp_speed: int,
    gravitonic_movement: bool,
    flare_mode: FlareConnectionMode,
    flare_depth: int = 1,
    flare_bfs_use_distance_prune: bool = True,
    diagnostics: DiagnosticNode | None = None,
    connection_route_algorithm: ConnectionRouteAlgorithm = (
        ConnectionRouteAlgorithm.PER_DEPTH_CENTER_ANNULUS
    ),
    include_illustrative_routes: bool = False,
    connection_routes_test_mode: bool = False,
    connection_routes_live_compare: bool = False,
    validate_illustrative_routes: bool = False,
) -> ConnectionRoutesOutcome:
    """Canonical planet pairs (lower id -> higher id) with direct and/or flare connectivity.

    With flares, ``flare_depth`` *N* is the **maximum hop count** (each hop is a normal move of
    at most ``max_travel`` or one flare), with at least one flare on the path. Annulus
    candidate pairs are built once (same spatial-index work for every *k*), then for each
    *k* = 1, 2, 3 in order we add pairs not already in a shallower layer, unioning to match the
    *k*‑or semantics.

    **Candidates:** the spatial index is queried twice: all planets with center distance
    ≤ ``max_travel`` (inner disc) and all within the flare reach disc (``scan_flare``). The
    expensive flare BFS runs only for pairs in the **annulus** (outer query minus inner
    membership by id): inner pairs are limited to the normal (direct) link check. Pairs with
    center separation ≤ ``max_travel`` that would still need a short flare are omitted from
    the dashed “flare” overlay by design.

    Set ``flare_bfs_use_distance_prune`` to False only for debugging; it disables the
    sound triangle-inequality bound from ``_max_flare_arrival_extent`` inside flare BFS.
    """
    if flare_depth < 1 or flare_depth > _MAX_FLARE_CHAIN_DEPTH:
        msg = f"flare_depth must be 1, 2, or 3, got {flare_depth}"
        raise ValueError(msg)
    max_travel = max_travel_distance(warp_speed, gravitonic_movement)
    movement = FlareMovementKind.GRAVITONIC if gravitonic_movement else FlareMovementKind.REGULAR
    use_flare_geometry = flare_mode is not FlareConnectionMode.OFF
    flares = flare_points_for_warp(warp_speed, movement) if use_flare_geometry else []

    scan_direct = max_travel + NORMAL_RADIUS
    scan_flare = scan_direct
    if use_flare_geometry and flares:
        extent = _max_flare_arrival_extent(flares)
        hop_loose = max(max_travel, extent)
        scan_flare = max(
            scan_flare,
            flare_depth * hop_loose + NORMAL_RADIUS,
        )

    index = _PlanetSpatialIndex(planets)
    sorted_planets = sorted(planets, key=lambda p: p.id)
    cr = diagnostics.child("connection_routes") if diagnostics is not None else None
    hop_loose = max_travel
    if use_flare_geometry and flares:
        hop_loose = max(max_travel, _max_flare_arrival_extent(flares))

    def _make_u_flare(
        algo: ConnectionRouteAlgorithm,
        diag: DiagnosticNode | None,
    ) -> set[tuple[int, int]] | None:
        if not use_flare_geometry or not flares or flare_mode is FlareConnectionMode.OFF:
            return None
        if algo is ConnectionRouteAlgorithm.DEFAULT:
            flare_layer = diag.child("flare_eligible_by_layer") if diag is not None else None
            if flare_layer is not None:
                flare_layer.values["maxK"] = int(min(_MAX_FLARE_CHAIN_DEPTH, flare_depth))
            e1, e2, e3 = _build_flare_eligible_by_layer(
                sorted_planets,
                index,
                flares,
                max_travel,
                scan_flare,
                scan_direct,
                min(_MAX_FLARE_CHAIN_DEPTH, flare_depth),
                use_distance_prune=flare_bfs_use_distance_prune,
                diagnostics=flare_layer,
            )
        else:
            fdiag = diag.child("flare_per_depth_center_union") if diag is not None else None
            e1, e2, e3 = _build_flare_eligible_per_depth_center_annuli(
                sorted_planets,
                index,
                flares,
                max_travel,
                hop_loose,
                min(_MAX_FLARE_CHAIN_DEPTH, flare_depth),
                use_distance_prune=flare_bfs_use_distance_prune,
                diagnostics=fdiag,
            )
        s: set[tuple[int, int]] = set()
        if flare_depth >= 1:
            s |= e1
        if flare_depth >= 2:
            s |= e2
        if flare_depth >= 3:
            s |= e3
        return s

    use_flare_discs = use_flare_geometry and bool(flares)
    max_path_hops = min(_MAX_FLARE_CHAIN_DEPTH, flare_depth)

    def _append_flare_row(
        planet_a: Planet,
        planet_b: Planet,
        out: list[dict[str, object]],
        validation_errors: list[str],
        run_label: str,
        include_illustr: bool,
        validate_illustr: bool,
    ) -> None:
        row: dict[str, object] = {
            "fromPlanetId": planet_a.id,
            "toPlanetId": planet_b.id,
            "viaFlare": True,
        }
        if include_illustr:
            pth = _pair_flare_path_either_direction(
                planet_a,
                planet_b,
                flares,
                max_path_hops,
                index,
                max_travel,
                use_distance_prune=flare_bfs_use_distance_prune,
            )
            if pth is not None:
                row["illustrativeRoute"] = pth
            if validate_illustr:
                ve = validate_illustrative_flare_route(planet_a, planet_b, pth, max_travel)
                if ve is not None:
                    validation_errors.append(f"({planet_a.id},{planet_b.id}) [{run_label}]: {ve}")
        out.append(row)

    def _emit(
        out: list[dict[str, object]],
        u_flare: set[tuple[int, int]] | None,
        validation_errors: list[str],
        run_label: str,
        include_illustr: bool,
        do_validate: bool,
    ) -> None:
        for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
            sorted_planets,
            index,
            max_travel=max_travel,
            scan_flare=scan_flare,
            scan_direct=scan_direct,
            use_flare_discs=use_flare_discs,
        ):
            direct = _pair_has_direct_connection(planet_a, planet_b, max_travel)
            pair_key = _canonical_pair_id(planet_a, planet_b)
            exclusive_flare = (
                u_flare is not None and pair_key in u_flare and not in_flare_inner and not direct
            )
            if flare_mode == FlareConnectionMode.OFF:
                if direct:
                    out.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": False,
                        }
                    )
            elif flare_mode == FlareConnectionMode.INCLUDE:
                if direct:
                    out.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": False,
                        }
                    )
                elif exclusive_flare:
                    _append_flare_row(
                        planet_a,
                        planet_b,
                        out,
                        validation_errors,
                        run_label,
                        include_illustr,
                        do_validate,
                    )
            elif flare_mode == FlareConnectionMode.ONLY:
                if exclusive_flare:
                    _append_flare_row(
                        planet_a,
                        planet_b,
                        out,
                        validation_errors,
                        run_label,
                        include_illustr,
                        do_validate,
                    )
            else:
                msg = f"unsupported FlareConnectionMode: {flare_mode!r}"
                raise ValueError(msg)

    def _flare_count(rs: list[dict[str, object]]) -> int:
        return sum(1 for r in rs if r.get("viaFlare") is True)

    if connection_routes_test_mode:
        val_d: list[str] = []
        val_p: list[str] = []
        r_d: list[dict[str, object]] = []
        r_p: list[dict[str, object]] = []
        d_node = cr.child("defaultAlgorithm") if cr is not None else None
        p_node = cr.child("perDepthCenterAnnulus") if cr is not None else None
        max_k_ab = min(_MAX_FLARE_CHAIN_DEPTH, flare_depth)
        if d_node is not None:
            d_node.values["maxTravel"] = max_travel
            d_node.values["scanFlare"] = scan_flare
            d_node.values["scanDirect"] = scan_direct
            d_node.values["hopLoose"] = hop_loose
            d_node.values["annulusInnerRadius"] = max_travel
            d_node.values["annulusOuterRadius"] = scan_flare
        if p_node is not None:
            p_node.values["maxTravel"] = max_travel
            p_node.values["hopLoose"] = hop_loose
            p_node.values["normalRadius"] = float(NORMAL_RADIUS)
            for kk in range(1, max_k_ab + 1):
                inn, outv = _per_depth_center_annulus_radii(kk, max_travel, hop_loose)
                p_node.values[f"perDepthAnnulusK{kk}Inner"] = inn
                p_node.values[f"perDepthAnnulusK{kk}Outer"] = outv
        t0 = time.perf_counter()
        if d_node is not None:
            with timed_section(d_node, "total"):
                u_d = _make_u_flare(ConnectionRouteAlgorithm.DEFAULT, d_node)
                _emit(r_d, u_d, val_d, "default", True, connection_routes_live_compare)
        else:
            u_d = _make_u_flare(ConnectionRouteAlgorithm.DEFAULT, None)
            _emit(r_d, u_d, val_d, "default", True, connection_routes_live_compare)
        t1 = time.perf_counter()
        if p_node is not None:
            with timed_section(p_node, "total"):
                u_p = _make_u_flare(ConnectionRouteAlgorithm.PER_DEPTH_CENTER_ANNULUS, p_node)
                _emit(
                    r_p, u_p, val_p, "perDepthCenterAnnulus", True, connection_routes_live_compare
                )
        else:
            u_p = _make_u_flare(ConnectionRouteAlgorithm.PER_DEPTH_CENTER_ANNULUS, None)
            _emit(
                r_p, u_p, val_p, "perDepthCenterAnnulus", True, connection_routes_live_compare
            )
        t2 = time.perf_counter()
        for r in (r_d, r_p):
            r.sort(key=lambda x: (int(x["fromPlanetId"]), int(x["toPlanetId"])))
        if connection_routes_live_compare:
            primary = r_d
        elif connection_route_algorithm is ConnectionRouteAlgorithm.PER_DEPTH_CENTER_ANNULUS:
            primary = r_p
        else:
            primary = r_d
        comparison: dict[str, object] = {
            "primaryAlgorithm": connection_route_algorithm.value,
            "liveCompareForcedPrimary": connection_routes_live_compare,
            "default": {
                "seconds": t1 - t0,
                "pairCount": len(r_d),
                "flareEdgeCount": _flare_count(r_d),
                "illustrativeValidationErrors": val_d,
                "routes": r_d,
            },
            "perDepthCenterAnnulus": {
                "seconds": t2 - t1,
                "pairCount": len(r_p),
                "flareEdgeCount": _flare_count(r_p),
                "illustrativeValidationErrors": val_p,
                "routes": r_p,
            },
        }
        _enrich_connection_route_comparison_diff(comparison)
        return ConnectionRoutesOutcome(routes=primary, connection_route_test=comparison)

    u_sel = _make_u_flare(connection_route_algorithm, cr)
    val: list[str] = []
    routes_out: list[dict[str, object]] = []
    do_ill = include_illustrative_routes
    if cr is not None:
        ar = cr.child("assemble_routes")
        with timed_section(ar, "total"):
            _emit(
                routes_out,
                u_sel,
                val,
                connection_route_algorithm.value,
                do_ill,
                validate_illustrative_routes,
            )
        ar.values["outRoutes"] = len(routes_out)
    else:
        _emit(
            routes_out,
            u_sel,
            val,
            connection_route_algorithm.value,
            do_ill,
            validate_illustrative_routes,
        )
    routes_out.sort(key=lambda r: (int(r["fromPlanetId"]), int(r["toPlanetId"])))
    test_payload: dict[str, object] | None = None
    if val:
        test_payload = {"illustrativeValidationErrors": val}
    return ConnectionRoutesOutcome(routes=routes_out, connection_route_test=test_payload)


def connection_routes_for_planets(
    planets: list[Planet],
    *,
    warp_speed: int,
    gravitonic_movement: bool,
    flare_mode: FlareConnectionMode,
    flare_depth: int = 1,
    flare_bfs_use_distance_prune: bool = True,
    diagnostics: DiagnosticNode | None = None,
) -> list[dict[str, bool | int]]:
    """Same as :func:`connection_routes_with_options` with default algorithm and no extras."""
    return connection_routes_with_options(
        planets,
        warp_speed=warp_speed,
        gravitonic_movement=gravitonic_movement,
        flare_mode=flare_mode,
        flare_depth=flare_depth,
        flare_bfs_use_distance_prune=flare_bfs_use_distance_prune,
        diagnostics=diagnostics,
    ).routes  # type: ignore[return-value]
