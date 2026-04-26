"""Flare and mixed normal–flare BFS pathfinding and illustrative route validation."""

from __future__ import annotations

import math
import time
from collections import deque

from api.concepts.planet_connections._constants import _FLARE_DISTANCE_BOUND_SLACK
from api.concepts.planet_connections._diagnostics import (
    _FlareBfsHotspotTimings,
    _FlareBfsMetrics,
    _LatticeBuildDiagnostics,
)
from api.concepts.planet_connections.lattice_enumeration import (
    _iter_flares_bfs_angular,
    _iter_normal_one_hop_integer_lattice,
)
from api.concepts.planet_connections.spatial_index import _PlanetSpatialIndex
from api.concepts.planet_connections.wells import (
    min_distance_point_to_simplified_normal_well,
    point_in_simplified_normal_well,
)
from api.concepts.warp_well import NORMAL_RADIUS, planet_is_in_debris_disk
from api.models.flare_point import FlarePoint
from api.models.planet import Planet


def _max_flare_arrival_extent(flares: list[FlarePoint]) -> float:
    best = 0.0
    for f in flares:
        ax, ay = f.arrival_offset
        best = max(best, math.hypot(ax, ay))
    return best


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
