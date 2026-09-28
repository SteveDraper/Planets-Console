"""Nearest-planet partition of the map rectangle.

Sphere maps place a 3 by 3 copy of each site and clip the diagram back to
``[0, width] x [0, height]``. An exact distance tie belongs to the lower planet id.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import shapely
from shapely.geometry import MultiPoint, Polygon, box
from shapely.geometry.polygon import orient

from api.errors import CoreAPIError

Point = tuple[float, float]


class TerritoryRingError(CoreAPIError):
    """A territory component with holes could not be cut into one boundary ring."""


@dataclass(frozen=True)
class TerritorySite:
    """One planet competing for team territory."""

    planet_id: int
    x: float
    y: float
    league_team_id: int


def _image_meets_rectangle(x: float, y: float, i: int, j: int, width: float, height: float) -> bool:
    """True when this torus image can be nearest for some point of the rectangle.

    The image's period cell is the set of points closer to it than to any other
    image of the same planet. Images whose period cell misses the rectangle never
    win a point there.
    """
    left = x + i * width - width / 2.0
    right = x + i * width + width / 2.0
    bottom = y + j * height - height / 2.0
    top = y + j * height + height / 2.0
    return right >= 0.0 and left <= width and top >= 0.0 and bottom <= height


def _replicated_sites(
    sites: Sequence[TerritorySite],
    *,
    width: float,
    height: float,
    sphere: bool,
) -> list[TerritorySite]:
    if not sphere:
        return list(sites)
    replicas: list[TerritorySite] = []
    for site in sites:
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                if not _image_meets_rectangle(site.x, site.y, i, j, width, height):
                    continue
                replicas.append(
                    TerritorySite(
                        planet_id=site.planet_id,
                        x=site.x + i * width,
                        y=site.y + j * height,
                        league_team_id=site.league_team_id,
                    )
                )
    return replicas


def _coincident_winners(sites: Sequence[TerritorySite]) -> list[TerritorySite]:
    """One site per location. The lower planet id wins a coincident tie."""
    winners: dict[Point, TerritorySite] = {}
    for site in sites:
        location = (float(site.x), float(site.y))
        current = winners.get(location)
        if current is None or site.planet_id < current.planet_id:
            winners[location] = site
    return list(winners.values())


def _team_regions(
    sites: Sequence[TerritorySite],
    *,
    rectangle: Polygon,
) -> dict[int, list[Polygon]]:
    """Voronoi cells unioned by league team and clipped to ``rectangle``."""
    points = MultiPoint([(site.x, site.y) for site in sites])
    extent = box(*shapely.union(points.envelope, rectangle).bounds)
    cells = shapely.voronoi_polygons(points, extend_to=extent, ordered=True).geoms
    cells_by_team: dict[int, list[Polygon]] = defaultdict(list)
    for site, cell in zip(sites, cells, strict=True):
        if site.league_team_id > 0:
            cells_by_team[site.league_team_id].append(cell)
    regions: dict[int, list[Polygon]] = {}
    for team_id, cells_for_team in cells_by_team.items():
        clipped = shapely.intersection(shapely.union_all(cells_for_team), rectangle)
        regions[team_id] = [
            polygon
            for polygon in shapely.get_parts(clipped)
            if isinstance(polygon, Polygon) and polygon.area > 0.0
        ]
    return regions


def _signed_area(ring: Sequence[Point]) -> float:
    area = 0.0
    count = len(ring)
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(index + 1) % count]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _even_odd_contains(ring: Sequence[Point], x: float, y: float) -> bool:
    inside = False
    count = len(ring)
    previous = count - 1
    for index in range(count):
        x1, y1 = ring[index]
        x0, y0 = ring[previous]
        if (y1 > y) != (y0 > y):
            crossing_x = (x0 - x1) * (y - y1) / (y0 - y1) + x1
            if x < crossing_x:
                inside = not inside
        previous = index
    return inside


def _open_ring(coords: Sequence[Sequence[float]]) -> list[Point]:
    return [(float(x), float(y)) for x, y in coords[:-1]]


def _drop_repeats(ring: Sequence[Point]) -> list[Point]:
    kept: list[Point] = []
    for vertex in ring:
        if not kept or vertex != kept[-1]:
            kept.append(vertex)
    while len(kept) > 1 and kept[0] == kept[-1]:
        kept.pop()
    return kept


def _splice_hole(ring: list[Point], hole: list[Point]) -> list[Point] | None:
    """Cut ``hole`` into ``ring`` along a rightward ray from its rightmost vertex.

    Returns ``None`` when the ray meets no edge of ``ring``.
    """
    hole_index = max(range(len(hole)), key=lambda index: hole[index])
    hole_x, hole_y = hole[hole_index]
    best: tuple[float, int] | None = None
    count = len(ring)
    for index in range(count):
        (x1, y1), (x2, y2) = ring[index], ring[(index + 1) % count]
        if (y1 > hole_y) == (y2 > hole_y):
            continue
        hit_x = x1 + (hole_y - y1) / (y2 - y1) * (x2 - x1)
        if hit_x >= hole_x and (best is None or hit_x < best[0]):
            best = (hit_x, index)
    if best is None:
        return None
    hit = (best[0], hole_y)
    edge = best[1]
    hole_loop = [hole[(hole_index + step) % len(hole)] for step in range(len(hole))]
    return _drop_repeats(
        [*ring[: edge + 1], hit, *hole_loop, hole[hole_index], hit, *ring[edge + 1 :]]
    )


def _single_ring(polygon: Polygon) -> list[Point]:
    """One closed boundary ring whose even-odd interior equals ``polygon``.

    Each hole is joined to the boundary by a zero-width cut. The result is checked
    against the polygon; a cut that fills a hole or loses area raises
    :class:`TerritoryRingError`.
    """
    oriented = orient(polygon, sign=1.0)
    ring = _open_ring(oriented.exterior.coords)
    holes = sorted(
        (_open_ring(interior.coords) for interior in oriented.interiors),
        key=lambda hole: max(hole),
        reverse=True,
    )
    for hole in holes:
        spliced = _splice_hole(ring, hole)
        if spliced is None:
            raise TerritoryRingError("territory hole cut found no boundary edge")
        ring = spliced
    if holes:
        tolerance = 1e-9 * max(1.0, polygon.area)
        probes = [Polygon(hole).representative_point() for hole in holes]
        inside = polygon.representative_point()
        if (
            abs(_signed_area(ring) - polygon.area) > tolerance
            or not _even_odd_contains(ring, inside.x, inside.y)
            or any(_even_odd_contains(ring, probe.x, probe.y) for probe in probes)
        ):
            raise TerritoryRingError("territory hole cut does not match the unioned region")
    return ring


def _ring_sort_key(ring: Sequence[Point]) -> tuple[float, float, tuple[Point, ...]]:
    return (min(vertex[0] for vertex in ring), min(vertex[1] for vertex in ring), tuple(ring))


def territory_components(
    sites: Sequence[TerritorySite],
    *,
    width: int,
    height: int,
    sphere: bool,
) -> list[tuple[int, list[Point]]]:
    """Painted components as ``(league_team_id, ring)``.

    Cells whose site has ``league_team_id <= 0`` are omitted. Same-team cells
    that share a border become one ring. A hole in that union is cut into the
    same ring so the hole is not filled.
    """
    if width <= 0 or height <= 0 or not sites:
        return []
    width_f = float(width)
    height_f = float(height)
    replicas = _replicated_sites(sites, width=width_f, height=height_f, sphere=sphere)
    regions = _team_regions(
        _coincident_winners(replicas),
        rectangle=box(0.0, 0.0, width_f, height_f),
    )
    components: list[tuple[int, list[Point]]] = []
    for team_id in sorted(regions):
        rings = sorted((_single_ring(polygon) for polygon in regions[team_id]), key=_ring_sort_key)
        components.extend((team_id, ring) for ring in rings)
    return components
