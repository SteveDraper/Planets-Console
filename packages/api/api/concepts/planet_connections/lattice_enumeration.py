"""Integer lattice and flare angular neighbor enumeration (one normal hop, flare order)."""

from __future__ import annotations

import bisect
import math
import time
from collections.abc import Iterator

from api.concepts.planet_connections._constants import (
    _FLARES_ANGULAR_ROWS,
    _LATTICE_FULL_DISK_ANG,
    _LATTICE_STRIDED_ANG,
)
from api.concepts.planet_connections._diagnostics import _LatticeBuildDiagnostics
from api.models.flare_point import FlarePoint
from api.models.planet import Planet


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
        rows.sort(key=lambda t: (t[1], t[0].arrival_offset[0], t[0].arrival_offset[1], t[2]))
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
    row = _get_lattice_angular_row(r, r2, strided=strided, lattice_diagnostics=lattice_diagnostics)
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
