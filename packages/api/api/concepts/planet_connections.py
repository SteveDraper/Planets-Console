"""Planet-to-planet travel reachability for one turn (warp, normal wells, optional flares).

Debris-disk planets use a simplified well: only the planet map cell counts as the well
(consistent with product guidance for this analytic).
"""

from __future__ import annotations

import math
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
from api.models.flare_point import FlarePoint
from api.models.planet import Planet

MAX_GRID_CELL_VISITS = 12_000
_MIN_EXTENT_FOR_CELL_SIZING = 1.0


class FlareConnectionMode(StrEnum):
    """How flare-assisted routes are combined with direct warp-well reachability."""

    OFF = "off"
    INCLUDE = "include"
    ONLY = "only"


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


def _pair_has_exclusive_flare_connection(
    planet_a: Planet,
    planet_b: Planet,
    max_travel: float,
    flares: list[FlarePoint],
) -> bool:
    """Reachable via a flare move ending in the other's well, but not a normal connection."""
    if not flares:
        return False
    if _pair_has_direct_connection(planet_a, planet_b, max_travel):
        return False
    return _reachable_via_flare(planet_a, planet_b, flares) or _reachable_via_flare(
        planet_b, planet_a, flares
    )


def _reachable_via_flare(
    from_planet: Planet,
    to_planet: Planet,
    flares: list[FlarePoint],
) -> bool:
    if not flares:
        return False
    ax, ay = float(from_planet.x), float(from_planet.y)
    for f in flares:
        # Do not require hypot(waypoint) <= warp^2. Host accepts waypoints farther than
        # warp squared; movement scales by warp^2/(way_x^2+way_y^2). Flare table rows are
        # authoritative for which (waypoint, arrival) pairs exist at this warp.
        ex = ax + float(f.arrival_offset[0])
        ey = ay + float(f.arrival_offset[1])
        if point_in_simplified_normal_well(to_planet, ex, ey):
            return True
    return False


def connection_routes_for_planets(
    planets: list[Planet],
    *,
    warp_speed: int,
    gravitonic_movement: bool,
    flare_mode: FlareConnectionMode,
) -> list[dict[str, bool | int]]:
    """Canonical planet pairs (lower id -> higher id) with direct and/or flare connectivity."""
    max_travel = max_travel_distance(warp_speed, gravitonic_movement)
    movement = FlareMovementKind.GRAVITONIC if gravitonic_movement else FlareMovementKind.REGULAR
    use_flare_geometry = flare_mode is not FlareConnectionMode.OFF
    flares = flare_points_for_warp(warp_speed, movement) if use_flare_geometry else []

    scan_direct = max_travel + NORMAL_RADIUS
    scan_flare = scan_direct
    if use_flare_geometry and flares:
        scan_flare = max(scan_flare, _max_flare_arrival_extent(flares) + NORMAL_RADIUS)

    index = _PlanetSpatialIndex(planets)
    sorted_planets = sorted(planets, key=lambda p: p.id)
    routes: list[dict[str, bool | int]] = []

    for planet_a in sorted_planets:
        radius = scan_flare if use_flare_geometry and flares else scan_direct
        candidates = list(
            index.iter_planets_within_radius(
                float(planet_a.x),
                float(planet_a.y),
                radius,
                min_planet_id_exclusive=planet_a.id,
            )
        )
        for planet_b in candidates:
            if planet_b.id <= planet_a.id:
                continue
            direct = _pair_has_direct_connection(planet_a, planet_b, max_travel)
            exclusive_flare = _pair_has_exclusive_flare_connection(
                planet_a, planet_b, max_travel, flares
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

    routes.sort(key=lambda r: (int(r["fromPlanetId"]), int(r["toPlanetId"])))
    return routes
