"""Uniform spatial grid over map coordinates for planet neighbor queries."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from api.concepts.planet_connections._constants import (
    _MIN_EXTENT_FOR_CELL_SIZING,
    MAX_GRID_CELL_VISITS,
)
from api.models.planet import Planet


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
