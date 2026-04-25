"""Planet-to-planet travel reachability for one turn (warp, normal wells, optional flares).

Debris-disk planets use a simplified well: only the planet map cell counts as the well
(consistent with product guidance for this analytic).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
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


class FlareConnectionMode(StrEnum):
    """How flare-assisted routes are combined with direct warp-well reachability."""

    OFF = "off"
    INCLUDE = "include"
    ONLY = "only"


@dataclass
class _FlareBfsMetrics:
    """Mutable counters for optional diagnostics (avoids per-pair child nodes in the BFS)."""

    bfs_runs: int = 0
    bfs_dequeues: int = 0
    bfs_enqueues: int = 0


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


def _point_lies_in_any_planet_well(qx: float, qy: float, planets: list[Planet]) -> bool:
    return any(point_in_simplified_normal_well(p, qx, qy) for p in planets)


def _iter_normal_one_hop_integer_lattice(
    px: int,
    py: int,
    max_travel: float,
    *,
    to_planet: Planet,
) -> Iterator[tuple[int, int]]:
    """Integer map cells to consider for one **normal** move (2D, Euclidean

    at most ``max_travel``). Excludes the no-op offset (0, 0).

    For small ``max_travel`` (floor \\ :math:`\\le` 18), the full open disk of integer
    offsets is used. For larger warps, a strided box plus a greedy step toward ``to_planet``
    and outer box corners keeps the search tractable.
    """
    if not math.isfinite(max_travel) or max_travel <= 0.0:
        return
    r2 = max_travel * max_travel
    r = int(min(math.floor(max_travel + 1e-9), 1_000_000))
    yielded: set[tuple[int, int]] = set()

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

    # Greedy: one step toward the destination (often needed before a table flare).
    tx, ty = int(to_planet.x), int(to_planet.y)
    vx, vy = float(tx - px), float(ty - py)
    dist = math.hypot(vx, vy)
    if dist > 1e-9:
        step = min(max_travel, dist)
        gx = int(round(px + (vx / dist) * step))
        gy = int(round(py + (vy / dist) * step))
        o = y_one(gx, gy)
        if o is not None:
            yield o

    if r > 0:
        for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (r, -r), (-r, r), (-r, -r)):
            o = y_one(px + dx, py + dy)
            if o is not None:
                yield o

    if r <= 18:
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
                o = y_one(px + dx, py + dy)
                if o is not None:
                    yield o
    else:
        # Strided 2D grid + axis sweeps; still includes greedy and box corners (above).
        step = max(1, r // 10)
        for dx in range(-r, r + 1, step):
            for dy in range(-r, r + 1, step):
                if float(dx) * float(dx) + float(dy) * float(dy) > r2 + 1e-3:
                    continue
                if dx == 0 and dy == 0:
                    continue
                o = y_one(px + dx, py + dy)
                if o is not None:
                    yield o
        sub = max(1, step // 2)
        for ddx in (-r, 0, r):
            for ddy in range(-r, r + 1, sub):
                o = y_one(px + ddx, py + ddy)
                if o is not None:
                    yield o
        for ddy in (-r, 0, r):
            for ddx in range(-r, r + 1, sub):
                o = y_one(px + ddx, py + ddy)
                if o is not None:
                    yield o


def _flare_path_state_exceeds_distance_bound(
    to_planet: Planet,
    max_hops: int,
    x: int,
    y: int,
    hops_completed: int,
    step_max: float,
    use_distance_prune: bool,
) -> bool:
    """Sound triangle-inequality bound: if True, this position cannot reach the goal in the
    remaining hop budget, so the state need not be expanded and children need not be generated.

    ``hops_completed`` is the number of hops already taken to arrive at ``(x, y)`` (same as
    ``hops_used`` when dequeuing a BFS state, or the child's hop count after the incoming move).
    """
    if not use_distance_prune or step_max <= 0.0:
        return False
    rem = max_hops - hops_completed
    d_to_well = min_distance_point_to_simplified_normal_well(float(x), float(y), to_planet)
    return d_to_well > rem * step_max + 1e-9


def _reachable_via_flare_limited_depth(
    from_planet: Planet,
    to_planet: Planet,
    flares: list[FlarePoint],
    max_depth: int,
    all_planets: list[Planet],
    max_travel: float,
    *,
    use_distance_prune: bool = True,
    bfs_metrics: _FlareBfsMetrics | None = None,
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
    while q:
        px, py, hops_used, used_flare = q.popleft()
        if bfs_metrics is not None:
            bfs_metrics.bfs_dequeues += 1
        if hops_used >= max_depth:
            continue
        # Cheapest cull: drop doomed states before enumerating normal neighbors / all flares.
        if _flare_path_state_exceeds_distance_bound(
            to_planet, max_depth, px, py, hops_used, step_max, use_distance_prune
        ):
            continue

        # Last hop, no flare used yet: may only use a flare (so the path includes ≥1 flare).
        last_hop_forces_flare = (hops_used == max_depth - 1) and (not used_flare)

        if not last_hop_forces_flare:
            for nx, ny in _iter_normal_one_hop_integer_lattice(
                px, py, max_travel, to_planet=to_planet
            ):
                nd = hops_used + 1
                if _flare_path_state_exceeds_distance_bound(
                    to_planet, max_depth, nx, ny, nd, step_max, use_distance_prune
                ):
                    continue
                fnx, fny = float(nx), float(ny)
                if point_in_simplified_normal_well(to_planet, fnx, fny) and used_flare:
                    return True
                if point_in_simplified_normal_well(to_planet, fnx, fny) and not used_flare:
                    # In destination well but no flare yet: invalid flare-assisted path; do not
                    # enqueue (same as for flares: cannot stage inside dest without a flare used).
                    continue
                if nd >= max_depth:
                    continue
                if (nx, ny, nd, used_flare) in seen:
                    continue
                if _point_lies_in_any_planet_well(fnx, fny, all_planets):
                    continue
                seen.add((nx, ny, nd, used_flare))
                q.append((nx, ny, nd, used_flare))
                if bfs_metrics is not None:
                    bfs_metrics.bfs_enqueues += 1

        for f in flares:
            ex = px + f.arrival_offset[0]
            ey = py + f.arrival_offset[1]
            nd = hops_used + 1
            if _flare_path_state_exceeds_distance_bound(
                to_planet, max_depth, ex, ey, nd, step_max, use_distance_prune
            ):
                continue
            fex, fey = float(ex), float(ey)
            new_used = True
            if point_in_simplified_normal_well(to_planet, fex, fey) and nd <= max_depth:
                return True
            if nd < max_depth and (ex, ey, nd, new_used) not in seen:
                if _point_lies_in_any_planet_well(fex, fey, all_planets):
                    continue
                seen.add((ex, ey, nd, new_used))
                q.append((ex, ey, nd, new_used))
                if bfs_metrics is not None:
                    bfs_metrics.bfs_enqueues += 1
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
    all_planets: list[Planet],
    max_travel: float,
    *,
    use_distance_prune: bool,
    bfs_metrics: _FlareBfsMetrics | None = None,
) -> bool:
    """Undirected flare test: ``planet_a`` first, then reverse only if well types differ."""
    ab = _reachable_via_flare_limited_depth(
        planet_a,
        planet_b,
        flares,
        max_hops,
        all_planets,
        max_travel,
        use_distance_prune=use_distance_prune,
        bfs_metrics=bfs_metrics,
    )
    if ab or _same_simplified_normal_well_type(planet_a, planet_b):
        return ab
    return _reachable_via_flare_limited_depth(
        planet_b,
        planet_a,
        flares,
        max_hops,
        all_planets,
        max_travel,
        use_distance_prune=use_distance_prune,
        bfs_metrics=bfs_metrics,
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


def _build_flare_eligible_by_layer(
    sorted_planets: list[Planet],
    index: _PlanetSpatialIndex,
    all_planets: list[Planet],
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

    m1 = _FlareBfsMetrics() if diagnostics is not None else None
    annulus1 = 0
    if diagnostics is not None:
        d1 = diagnostics.child("flare_transitive_k1")
        d1.values["k"] = 1
        with timed_section(d1, "total"):
            for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
                sorted_planets,
                index,
                max_travel=max_travel,
                scan_flare=scan_flare,
                scan_direct=scan_direct,
                use_flare_discs=True,
            ):
                if in_flare_inner:
                    continue
                annulus1 += 1
                key = _canonical_pair_id(planet_a, planet_b)
                if not _pair_reachable_in_k_normal_moves(
                    planet_a, planet_b, max_travel, 1
                ) and _pair_reachable_via_flare_either_direction(
                    planet_a,
                    planet_b,
                    flares,
                    1,
                    all_planets,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m1,
                ):
                    e1.add(key)
        d1.values["annulusPairs"] = annulus1
        d1.values["connectionsFoundInLayer"] = len(e1)
        d1.values["cumulativeConnections"] = len(e1)
        if m1 is not None:
            d1.values["bfsRuns"] = m1.bfs_runs
            d1.values["intermediateRoutePoints"] = m1.bfs_dequeues
            d1.values["searchEnqueues"] = m1.bfs_enqueues
    else:
        for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
            sorted_planets,
            index,
            max_travel=max_travel,
            scan_flare=scan_flare,
            scan_direct=scan_direct,
            use_flare_discs=True,
        ):
            if in_flare_inner:
                continue
            key = _canonical_pair_id(planet_a, planet_b)
            if not _pair_reachable_in_k_normal_moves(
                planet_a, planet_b, max_travel, 1
            ) and _pair_reachable_via_flare_either_direction(
                planet_a,
                planet_b,
                flares,
                1,
                all_planets,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e1.add(key)

    if max_k < 2:
        return (e1, e2, e3)

    m2 = _FlareBfsMetrics() if diagnostics is not None else None
    annulus2 = 0
    if diagnostics is not None:
        d2 = diagnostics.child("flare_transitive_k2")
        d2.values["k"] = 2
        with timed_section(d2, "total"):
            for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
                sorted_planets,
                index,
                max_travel=max_travel,
                scan_flare=scan_flare,
                scan_direct=scan_direct,
                use_flare_discs=True,
            ):
                if in_flare_inner:
                    continue
                annulus2 += 1
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
                    all_planets,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m2,
                ):
                    e2.add(key)
        d2.values["annulusPairs"] = annulus2
        d2.values["connectionsFoundInLayer"] = len(e2)
        d2.values["cumulativeConnections"] = len(e1) + len(e2)
        if m2 is not None:
            d2.values["bfsRuns"] = m2.bfs_runs
            d2.values["intermediateRoutePoints"] = m2.bfs_dequeues
            d2.values["searchEnqueues"] = m2.bfs_enqueues
    else:
        for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
            sorted_planets,
            index,
            max_travel=max_travel,
            scan_flare=scan_flare,
            scan_direct=scan_direct,
            use_flare_discs=True,
        ):
            if in_flare_inner:
                continue
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
                all_planets,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e2.add(key)

    if max_k < 3:
        return (e1, e2, e3)
    e12 = e1 | e2

    m3 = _FlareBfsMetrics() if diagnostics is not None else None
    annulus3 = 0
    if diagnostics is not None:
        d3 = diagnostics.child("flare_transitive_k3")
        d3.values["k"] = 3
        with timed_section(d3, "total"):
            for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
                sorted_planets,
                index,
                max_travel=max_travel,
                scan_flare=scan_flare,
                scan_direct=scan_direct,
                use_flare_discs=True,
            ):
                if in_flare_inner:
                    continue
                annulus3 += 1
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
                    all_planets,
                    max_travel,
                    use_distance_prune=use_distance_prune,
                    bfs_metrics=m3,
                ):
                    e3.add(key)
        d3.values["annulusPairs"] = annulus3
        d3.values["connectionsFoundInLayer"] = len(e3)
        d3.values["cumulativeConnections"] = len(e1) + len(e2) + len(e3)
        if m3 is not None:
            d3.values["bfsRuns"] = m3.bfs_runs
            d3.values["intermediateRoutePoints"] = m3.bfs_dequeues
            d3.values["searchEnqueues"] = m3.bfs_enqueues
    else:
        for planet_a, planet_b, in_flare_inner in _iter_flare_candidate_edges(
            sorted_planets,
            index,
            max_travel=max_travel,
            scan_flare=scan_flare,
            scan_direct=scan_direct,
            use_flare_discs=True,
        ):
            if in_flare_inner:
                continue
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
                all_planets,
                max_travel,
                use_distance_prune=use_distance_prune,
                bfs_metrics=None,
            ):
                e3.add(key)
    return (e1, e2, e3)


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
    """Canonical planet pairs (lower id -> higher id) with direct and/or flare connectivity.

    With flares, ``flare_depth`` *N* is the **maximum hop count** (each hop is a normal move of
    at most ``max_travel`` or one flare), with at least one flare on the path. Eligible pairs
    are precomputed in independent passes for *k* = 1, 2, 3 (skipping a pair in later passes
    if it is already in a shallower layer), then unioned to match the *k*‑or semantics.

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
    routes: list[dict[str, bool | int]] = []

    cr = diagnostics.child("connection_routes") if diagnostics is not None else None

    u_flare: set[tuple[int, int]] | None = None
    if use_flare_geometry and flares and flare_mode is not FlareConnectionMode.OFF:
        flare_layer_diag: DiagnosticNode | None = (
            cr.child("flare_eligible_by_layer") if cr is not None else None
        )
        if flare_layer_diag is not None:
            flare_layer_diag.values["maxK"] = int(min(_MAX_FLARE_CHAIN_DEPTH, flare_depth))
        e1, e2, e3 = _build_flare_eligible_by_layer(
            sorted_planets,
            index,
            sorted_planets,
            flares,
            max_travel,
            scan_flare,
            scan_direct,
            min(_MAX_FLARE_CHAIN_DEPTH, flare_depth),
            use_distance_prune=flare_bfs_use_distance_prune,
            diagnostics=flare_layer_diag,
        )
        u_flare = set()
        if flare_depth >= 1:
            u_flare |= e1
        if flare_depth >= 2:
            u_flare |= e2
        if flare_depth >= 3:
            u_flare |= e3

    use_flare_discs = use_flare_geometry and bool(flares)

    def _emit_routes() -> None:
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
                    routes.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": False,
                        }
                    )
            elif flare_mode == FlareConnectionMode.INCLUDE:
                if direct:
                    routes.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": False,
                        }
                    )
                elif exclusive_flare:
                    routes.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": True,
                        }
                    )
            elif flare_mode == FlareConnectionMode.ONLY:
                if exclusive_flare:
                    routes.append(
                        {
                            "fromPlanetId": planet_a.id,
                            "toPlanetId": planet_b.id,
                            "viaFlare": True,
                        }
                    )
            else:
                msg = f"unsupported FlareConnectionMode: {flare_mode!r}"
                raise ValueError(msg)

    if cr is not None:
        ar = cr.child("assemble_routes")
        with timed_section(ar, "total"):
            _emit_routes()
        ar.values["outRoutes"] = len(routes)
    else:
        _emit_routes()

    routes.sort(key=lambda r: (int(r["fromPlanetId"]), int(r["toPlanetId"])))
    return routes
