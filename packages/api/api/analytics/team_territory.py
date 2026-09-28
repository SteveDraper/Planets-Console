"""Nearest-planet partition of the map rectangle.

Sphere maps place a 3 by 3 copy of each site and clip the diagram back to
``[0, width] x [0, height]``. An exact distance tie belongs to the lower planet id.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]

_LOSE_COINCIDENT_TIE = object()
_AREA_EPSILON = 1e-8


@dataclass(frozen=True)
class TerritorySite:
    """One planet competing for team territory."""

    planet_id: int
    x: float
    y: float
    league_team_id: int


def _quantize(value: float) -> float:
    return round(float(value), 8)


def _point(x: float, y: float) -> Point:
    return (_quantize(x), _quantize(y))


def _signed_area(ring: Sequence[Point]) -> float:
    area = 0.0
    count = len(ring)
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(index + 1) % count]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _dedupe_closed(ring: Sequence[Point]) -> list[Point]:
    deduped: list[Point] = []
    for vertex in ring:
        if not deduped or vertex != deduped[-1]:
            deduped.append(vertex)
    if len(deduped) > 1 and deduped[0] == deduped[-1]:
        deduped.pop()
    return deduped


def _ensure_ccw(ring: Sequence[Point]) -> list[Point]:
    ordered = list(ring)
    if _signed_area(ordered) < 0:
        ordered.reverse()
    return ordered


def _rectangle(width: float, height: float) -> list[Point]:
    return [(0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height))]


def _inside_halfplane(vertex: Point, nx: float, ny: float, limit: float) -> bool:
    return nx * vertex[0] + ny * vertex[1] <= limit + 1e-9


def _segment_hit(
    start: Point,
    end: Point,
    nx: float,
    ny: float,
    limit: float,
) -> Point:
    start_side = nx * start[0] + ny * start[1]
    end_side = nx * end[0] + ny * end[1]
    denominator = start_side - end_side
    if abs(denominator) < 1e-15:
        return end
    parameter = (start_side - limit) / denominator
    parameter = min(1.0, max(0.0, parameter))
    return _point(
        start[0] + parameter * (end[0] - start[0]),
        start[1] + parameter * (end[1] - start[1]),
    )


def _clip_halfplane(ring: Sequence[Point], nx: float, ny: float, limit: float) -> list[Point]:
    if len(ring) < 3:
        return []
    output: list[Point] = []
    previous = ring[-1]
    previous_inside = _inside_halfplane(previous, nx, ny, limit)
    for current in ring:
        current_inside = _inside_halfplane(current, nx, ny, limit)
        if current_inside:
            if not previous_inside:
                output.append(_segment_hit(previous, current, nx, ny, limit))
            output.append(_point(*current))
        elif previous_inside:
            output.append(_segment_hit(previous, current, nx, ny, limit))
        previous = current
        previous_inside = current_inside
    output = _dedupe_closed(output)
    if len(output) < 3 or abs(_signed_area(output)) <= _AREA_EPSILON:
        return []
    return output


def _competitor_plane(owner: TerritorySite, other: TerritorySite):
    """Half-plane of points closer to ``owner`` than to ``other``.

    Coincident sites are an exact tie: the lower planet id keeps the cell and
    the higher planet id loses it. Otherwise the shared boundary stays in both
    cells (zero area).
    """
    delta_x = other.x - owner.x
    delta_y = other.y - owner.y
    if delta_x == 0.0 and delta_y == 0.0:
        if owner.planet_id <= other.planet_id:
            return None
        return _LOSE_COINCIDENT_TIE
    return (
        2.0 * delta_x,
        2.0 * delta_y,
        other.x * other.x - owner.x * owner.x + other.y * other.y - owner.y * owner.y,
    )


def _cell_radius(owner: TerritorySite, ring: Sequence[Point]) -> float:
    return max(math.hypot(vertex[0] - owner.x, vertex[1] - owner.y) for vertex in ring)


def _cell(
    owner: TerritorySite,
    sites: Sequence[TerritorySite],
    *,
    width: float,
    height: float,
) -> list[Point]:
    ring = _rectangle(width, height)
    competitors: list[tuple[float, TerritorySite]] = []
    for other in sites:
        if other is owner:
            continue
        delta_x = other.x - owner.x
        delta_y = other.y - owner.y
        competitors.append((delta_x * delta_x + delta_y * delta_y, other))
    competitors.sort(key=lambda item: item[0])
    for distance_squared, other in competitors:
        # A site beyond twice the cell radius cannot be nearest anywhere in the cell.
        radius = _cell_radius(owner, ring)
        if distance_squared > (2.0 * radius + 1e-6) ** 2:
            break
        plane = _competitor_plane(owner, other)
        if plane is None:
            continue
        if plane is _LOSE_COINCIDENT_TIE:
            return []
        ring = _clip_halfplane(ring, plane[0], plane[1], plane[2])
        if not ring:
            return []
    return _ensure_ccw(ring)


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


def _on_open_segment(point: Point, start: Point, end: Point) -> bool:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length <= 1e-12:
        return False
    cross = abs((point[0] - start[0]) * delta_y - (point[1] - start[1]) * delta_x)
    if cross > 1e-7 * length:
        return False
    dot = (point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y
    tolerance = 1e-7 * length
    return tolerance < dot < length * length - tolerance


def _split_t_junctions(rings: Sequence[Sequence[Point]]) -> list[tuple[Point, Point]]:
    vertices: list[Point] = []
    edges: list[tuple[Point, Point]] = []
    for ring in rings:
        count = len(ring)
        for index, start in enumerate(ring):
            end = ring[(index + 1) % count]
            if start != end:
                edges.append((start, end))
                vertices.append(start)
    unique = list(dict.fromkeys(vertices))
    cell = 64.0
    buckets: dict[tuple[int, int], list[Point]] = defaultdict(list)
    for vertex in unique:
        buckets[(int(vertex[0] // cell), int(vertex[1] // cell))].append(vertex)
    split: list[tuple[Point, Point]] = []
    for start, end in edges:
        min_x, max_x = min(start[0], end[0]), max(start[0], end[0])
        min_y, max_y = min(start[1], end[1]), max(start[1], end[1])
        candidates: list[Point] = []
        for bucket_x in range(int(min_x // cell) - 1, int(max_x // cell) + 2):
            for bucket_y in range(int(min_y // cell) - 1, int(max_y // cell) + 2):
                candidates.extend(buckets.get((bucket_x, bucket_y), ()))
        mids = [vertex for vertex in candidates if _on_open_segment(vertex, start, end)]
        mids.sort(key=lambda vertex: (vertex[0] - start[0]) ** 2 + (vertex[1] - start[1]) ** 2)
        chain = [start, *mids, end]
        for index in range(len(chain) - 1):
            if chain[index] != chain[index + 1]:
                split.append((chain[index], chain[index + 1]))
    return split


def _cancel_shared_edges(edges: Sequence[tuple[Point, Point]]) -> list[tuple[Point, Point]]:
    counts: dict[tuple[Point, Point], int] = defaultdict(int)
    for start, end in edges:
        if start != end:
            counts[(start, end)] += 1
    for start, end in list(counts):
        if (start, end) > (end, start):
            continue
        cancel = min(counts[(start, end)], counts.get((end, start), 0))
        if cancel:
            counts[(start, end)] -= cancel
            counts[(end, start)] -= cancel
    remaining: list[tuple[Point, Point]] = []
    for edge, count in counts.items():
        remaining.extend([edge] * count)
    return remaining


def _clockwise_turn(previous: Point, current: Point, candidate: Point) -> float:
    in_x = current[0] - previous[0]
    in_y = current[1] - previous[1]
    out_x = candidate[0] - current[0]
    out_y = candidate[1] - current[1]
    return math.atan2(in_x * out_y - in_y * out_x, in_x * out_x + in_y * out_y)


def _trace_cycles(edges: Sequence[tuple[Point, Point]]) -> list[list[Point]]:
    outgoing: dict[Point, list[Point]] = defaultdict(list)
    for start, end in edges:
        outgoing[start].append(end)
    cycles: list[list[Point]] = []
    for start in list(outgoing):
        while outgoing[start]:
            first = outgoing[start].pop()
            ring = _walk_cycle(outgoing, start, first)
            if ring is not None:
                cycles.append(ring)
    return cycles


def _walk_cycle(
    outgoing: dict[Point, list[Point]],
    start: Point,
    first: Point,
) -> list[Point] | None:
    ring = [start]
    previous = start
    current = first
    for _ in range(100000):
        if current == start:
            if len(ring) >= 3 and abs(_signed_area(ring)) > _AREA_EPSILON:
                return ring
            return None
        ring.append(current)
        options = outgoing.get(current)
        if not options:
            return None
        if len(options) == 1:
            nxt = options.pop()
        else:
            chosen = min(
                range(len(options)),
                key=lambda index: _clockwise_turn(previous, current, options[index]),
            )
            nxt = options.pop(chosen)
        previous, current = current, nxt
    return None


def _point_in_ring(ring: Sequence[Point], x: float, y: float) -> bool:
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


def _bridge_hole(outer: Sequence[Point], hole: Sequence[Point]) -> list[Point]:
    """Join a clockwise hole into a counterclockwise outer ring with a cut."""
    hole_index = max(range(len(hole)), key=lambda index: (hole[index][0], hole[index][1]))
    hole_x, hole_y = hole[hole_index]
    best_distance: float | None = None
    best_edge: int | None = None
    best_hit: Point | None = None
    count = len(outer)
    for index in range(count):
        start = outer[index]
        end = outer[(index + 1) % count]
        if (start[1] > hole_y) == (end[1] > hole_y):
            continue
        if abs(end[1] - start[1]) <= 1e-15:
            continue
        parameter = (hole_y - start[1]) / (end[1] - start[1])
        hit_x = start[0] + parameter * (end[0] - start[0])
        if hit_x < hole_x - 1e-9:
            continue
        distance = hit_x - hole_x
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_edge = index
            best_hit = _point(hit_x, hole_y)
    if best_edge is None or best_hit is None:
        return list(outer)
    return _splice_hole(outer, hole, best_edge, best_hit, hole_index)


def _splice_hole(
    outer: Sequence[Point],
    hole: Sequence[Point],
    edge_index: int,
    hit: Point,
    hole_index: int,
) -> list[Point]:
    count = len(outer)
    edge_start = outer[edge_index]
    edge_end = outer[(edge_index + 1) % count]
    ring: list[Point] = []
    if hit != edge_start and hit != edge_end:
        ring.append(hit)
        cursor = (edge_index + 1) % count
        for _ in range(count):
            ring.append(outer[cursor])
            cursor = (cursor + 1) % count
        ring.append(hit)
    else:
        start_index = edge_index if hit == edge_start else (edge_index + 1) % count
        ring.extend(outer[(start_index + step) % count] for step in range(count))
        ring.append(outer[start_index])
    ring.extend(hole[(hole_index + step) % len(hole)] for step in range(len(hole)))
    ring.append(hole[hole_index])
    return _dedupe_closed(ring)


def _union_rings(rings: Sequence[Sequence[Point]]) -> list[list[Point]]:
    if not rings:
        return []
    oriented = [_ensure_ccw(ring) for ring in rings if len(ring) >= 3]
    if not oriented:
        return []
    if len(oriented) == 1:
        return oriented
    remaining = _cancel_shared_edges(_split_t_junctions(oriented))
    cycles = _trace_cycles(remaining)
    outers: list[list[Point]] = []
    holes: list[list[Point]] = []
    for cycle in cycles:
        if _signed_area(cycle) > 0:
            outers.append(cycle)
        else:
            # Negative area is a clockwise hole. The bridge keeps that winding.
            holes.append(cycle)
    assigned: list[list[list[Point]]] = [[] for _ in outers]
    for hole in holes:
        sample = hole[0]
        container: int | None = None
        container_area: float | None = None
        for index, outer in enumerate(outers):
            if not _point_in_ring(outer, sample[0], sample[1]):
                continue
            area = abs(_signed_area(outer))
            if container is None or container_area is None or area < container_area:
                container = index
                container_area = area
        if container is not None:
            assigned[container].append(hole)
    components: list[list[Point]] = []
    for outer, outer_holes in zip(outers, assigned, strict=True):
        ring = outer
        ordered_holes = sorted(
            outer_holes,
            key=lambda item: max(vertex[0] for vertex in item),
            reverse=True,
        )
        for hole in ordered_holes:
            ring = _bridge_hole(ring, hole)
        components.append(ring)
    return components


def _clamp_ring(ring: Sequence[Point], width: float, height: float) -> list[Point]:
    clamped = [_point(min(max(x, 0.0), width), min(max(y, 0.0), height)) for x, y in ring]
    return _dedupe_closed(clamped)


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
    cells_by_team: dict[int, list[list[Point]]] = defaultdict(list)
    for replica in replicas:
        ring = _cell(replica, replicas, width=width_f, height=height_f)
        if len(ring) < 3 or replica.league_team_id <= 0:
            continue
        cells_by_team[replica.league_team_id].append(ring)
    components: list[tuple[int, list[Point]]] = []
    for team_id in sorted(cells_by_team):
        rings = [
            clamped
            for ring in _union_rings(cells_by_team[team_id])
            if len(clamped := _clamp_ring(ring, width_f, height_f)) >= 3
            and abs(_signed_area(clamped)) > _AREA_EPSILON
        ]
        rings.sort(key=_ring_sort_key)
        components.extend((team_id, ring) for ring in rings)
    return components
