"""Nearest-planet partition of the map rectangle.

The rectangle has size ``mapwidth`` by ``mapheight`` and is centered on the
classical Nu origin ``(2000, 2000)``. Sphere maps place a 3 by 3 copy of each
site and clip the diagram back to that rectangle. An exact distance tie belongs
to the lower planet id.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import shapely
from shapely.affinity import translate
from shapely.geometry import MultiPoint, Polygon, box
from shapely.geometry.polygon import orient

from api.concepts.homeworld_layout import DEFAULT_MAP_CENTER_XY
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


@dataclass(frozen=True)
class MapRectangle:
    """Axis-aligned fundamental domain, ``width`` by ``height`` from ``left, bottom``."""

    left: float
    bottom: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def top(self) -> float:
        return self.bottom + self.height


def nu_map_rectangle(width: int, height: int) -> MapRectangle:
    """Map rectangle centered on the classical Nu origin."""
    center_x, center_y = DEFAULT_MAP_CENTER_XY
    return MapRectangle(
        left=center_x - width / 2.0,
        bottom=center_y - height / 2.0,
        width=float(width),
        height=float(height),
    )


def _image_meets_rectangle(
    x: float,
    y: float,
    i: int,
    j: int,
    rectangle: MapRectangle,
) -> bool:
    """True when this torus image can be nearest for some point of the rectangle.

    The image's period cell is the set of points closer to it than to any other
    image of the same planet. Images whose period cell misses the rectangle never
    win a point there.
    """
    left = x + i * rectangle.width - rectangle.width / 2.0
    right = x + i * rectangle.width + rectangle.width / 2.0
    bottom = y + j * rectangle.height - rectangle.height / 2.0
    top = y + j * rectangle.height + rectangle.height / 2.0
    return (
        right >= rectangle.left
        and left <= rectangle.right
        and top >= rectangle.bottom
        and bottom <= rectangle.top
    )


def _replicated_sites(
    sites: Sequence[TerritorySite],
    *,
    rectangle: MapRectangle,
    sphere: bool,
) -> list[TerritorySite]:
    if not sphere:
        return list(sites)
    replicas: list[TerritorySite] = []
    for site in sites:
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                if not _image_meets_rectangle(site.x, site.y, i, j, rectangle):
                    continue
                replicas.append(
                    TerritorySite(
                        planet_id=site.planet_id,
                        x=site.x + i * rectangle.width,
                        y=site.y + j * rectangle.height,
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


# Shared borders sit on the order of 0 LY. Unowned gaps are tens of LY wide.
TOUCH_GAP_LY = 1.0


def _period_shifts(rectangle: MapRectangle, *, sphere: bool) -> list[Point]:
    """Translations under which a clipped region is the same territory."""
    if not sphere:
        return [(0.0, 0.0)]
    return [(i * rectangle.width, j * rectangle.height) for i in (-1, 0, 1) for j in (-1, 0, 1)]


def _touching_teams(
    regions: dict[int, list[Polygon]],
    *,
    rectangle: MapRectangle,
    sphere: bool,
) -> dict[int, set[int]]:
    """League teams whose painted regions meet, including across a float gap.

    On a sphere the rectangle edges are seams, so a border lying on an edge is
    found by comparing against the periodic images of the other region.
    """
    geoms = {team_id: shapely.union_all(polygons) for team_id, polygons in regions.items()}
    shifts = _period_shifts(rectangle, sphere=sphere)
    team_ids = sorted(geoms)
    neighbors: dict[int, set[int]] = {team_id: set() for team_id in team_ids}
    for index, left_id in enumerate(team_ids):
        for right_id in team_ids[index + 1 :]:
            if any(
                geoms[left_id].distance(translate(geoms[right_id], xoff=dx, yoff=dy))
                <= TOUCH_GAP_LY
                for dx, dy in shifts
            ):
                neighbors[left_id].add(right_id)
                neighbors[right_id].add(left_id)
    return neighbors


def territory_partition(
    sites: Sequence[TerritorySite],
    *,
    width: int,
    height: int,
    sphere: bool,
) -> tuple[list[tuple[int, list[Point]]], dict[int, set[int]]]:
    """Painted components and which league teams share a border.

    Components are ``(league_team_id, ring)``. Cells whose site has
    ``league_team_id <= 0`` are omitted. Same-team cells that share a border
    become one ring. A hole in that union is cut into the same ring so the hole
    is not filled.
    """
    if width <= 0 or height <= 0 or not sites:
        return [], {}
    rectangle = nu_map_rectangle(width, height)
    replicas = _replicated_sites(sites, rectangle=rectangle, sphere=sphere)
    regions = _team_regions(
        _coincident_winners(replicas),
        rectangle=box(rectangle.left, rectangle.bottom, rectangle.right, rectangle.top),
    )
    components: list[tuple[int, list[Point]]] = []
    for team_id in sorted(regions):
        rings = sorted((_single_ring(polygon) for polygon in regions[team_id]), key=_ring_sort_key)
        components.extend((team_id, ring) for ring in rings)
    return components, _touching_teams(regions, rectangle=rectangle, sphere=sphere)
