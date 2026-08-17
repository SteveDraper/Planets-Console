"""Ships, planets, and cartography features within a light-year disk.

**MCP disk proximity** is the first-slice product query for this math ([ADR 0016],
[ADR 0021]). Callers pass a stored turn and a Euclidean disk on the map plane
(1 map unit = 1 ly). This is not the planets-only spatial index used by
Connections (``iter_planets_within_radius``), and it is not ``sample_at`` (a
point sample). Minefields are out of scope.

Hits are points or disks:

- **Points** (ships, planets, wormhole ends): ``dist(query, object) <= radius_ly``.
- **Disks** (ion storms, nebulae, star clusters, black holes, debris disks):
  query and feature disks overlap, ``dist(centers) <= radius_ly + feature_radius``.

Star-cluster ``radius`` is the outer radiation halo (``max`` of lethal core and
``sqrt(mass)``). Black-hole ``radius`` is the outer ergosphere. Ion-storm,
nebula, and debris-disk radii are the stored circle radii. Cloudy ion storms
contribute one hit per overlapping circle. Debris-disk seeds are planets with
``debrisdisk > 1`` (planetoids ``== 1`` are planets only). Wormhole hits are
entrances, plus a known exit that is not some other wormhole's entrance.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from api.concepts.stellar_cartography.black_holes import ergosphere_outer_radius
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.concepts.stellar_cartography.star_clusters import halo_radius_ly
from api.models.game import TurnInfo
from api.models.planet import Planet
from api.models.space import Star, Wormhole

INCLUDE_SHIPS = "ships"
INCLUDE_PLANETS = "planets"
INCLUDE_CARTOGRAPHY = "cartography"

KIND_SHIP = "ship"
KIND_PLANET = "planet"
KIND_ION_STORM = "ion_storm"
KIND_NEBULA = "nebula"
KIND_STAR_CLUSTER = "star_cluster"
KIND_BLACK_HOLE = "black_hole"
KIND_WORMHOLE = "wormhole"
KIND_DEBRIS_DISK = "debris_disk"

_ALL_INCLUDE = frozenset({INCLUDE_SHIPS, INCLUDE_PLANETS, INCLUDE_CARTOGRAPHY})


@dataclass(frozen=True)
class DiskProximityHit:
    """One object whose point or disk intersects the query disk."""

    kind: str
    id: int
    x: int
    y: int
    radius: float | None = None


def disk_proximity(
    turn: TurnInfo,
    x: float,
    y: float,
    radius_ly: float,
    include: Iterable[str] | None = None,
) -> list[DiskProximityHit]:
    """Return ships, planets, and cartography features within ``radius_ly`` of ``(x, y)``.

    ``include`` selects ``ships``, ``planets``, and/or ``cartography``. Omit it
    (or pass ``None``) to include all three. An empty iterable yields no hits.
    """
    if radius_ly < 0:
        raise ValueError("radius_ly must be >= 0")
    selected = _resolve_include(include)
    hits: list[DiskProximityHit] = []
    if INCLUDE_SHIPS in selected:
        hits.extend(_ship_hits(turn, x, y, radius_ly))
    if INCLUDE_PLANETS in selected:
        hits.extend(_planet_hits(turn, x, y, radius_ly))
    if INCLUDE_CARTOGRAPHY in selected:
        hits.extend(_cartography_hits(turn, x, y, radius_ly))
    hits.sort(key=lambda hit: (distance_ly(x, y, hit.x, hit.y), hit.kind, hit.id, hit.x, hit.y))
    return hits


def _resolve_include(include: Iterable[str] | None) -> frozenset[str]:
    if include is None:
        return _ALL_INCLUDE
    if isinstance(include, str):
        selected = frozenset({include})
    else:
        selected = frozenset(include)
    unknown = selected - _ALL_INCLUDE
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown disk proximity include: {names}")
    return selected


def _point_hit(
    kind: str,
    obj_id: int,
    px: int,
    py: int,
    qx: float,
    qy: float,
    radius_ly: float,
) -> DiskProximityHit | None:
    if distance_ly(qx, qy, px, py) <= radius_ly:
        return DiskProximityHit(kind=kind, id=obj_id, x=px, y=py)
    return None


def _disk_hit(
    kind: str,
    obj_id: int,
    px: int,
    py: int,
    feature_radius: float,
    qx: float,
    qy: float,
    radius_ly: float,
) -> DiskProximityHit | None:
    if distance_ly(qx, qy, px, py) <= radius_ly + feature_radius:
        return DiskProximityHit(
            kind=kind,
            id=obj_id,
            x=px,
            y=py,
            radius=feature_radius,
        )
    return None


def _ship_hits(turn: TurnInfo, qx: float, qy: float, radius_ly: float) -> list[DiskProximityHit]:
    hits: list[DiskProximityHit] = []
    for ship in turn.ships:
        hit = _point_hit(KIND_SHIP, ship.id, ship.x, ship.y, qx, qy, radius_ly)
        if hit is not None:
            hits.append(hit)
    return hits


def _planet_hits(turn: TurnInfo, qx: float, qy: float, radius_ly: float) -> list[DiskProximityHit]:
    hits: list[DiskProximityHit] = []
    for planet in turn.planets:
        hit = _point_hit(KIND_PLANET, planet.id, planet.x, planet.y, qx, qy, radius_ly)
        if hit is not None:
            hits.append(hit)
    return hits


def _cartography_hits(
    turn: TurnInfo, qx: float, qy: float, radius_ly: float
) -> list[DiskProximityHit]:
    hits: list[DiskProximityHit] = []
    for storm in turn.ionstorms:
        hit = _disk_hit(
            KIND_ION_STORM, storm.id, storm.x, storm.y, float(storm.radius), qx, qy, radius_ly
        )
        if hit is not None:
            hits.append(hit)
    for nebula in turn.nebulas:
        hit = _disk_hit(
            KIND_NEBULA, nebula.id, nebula.x, nebula.y, float(nebula.radius), qx, qy, radius_ly
        )
        if hit is not None:
            hits.append(hit)
    for star in turn.stars:
        hit = _disk_hit(
            KIND_STAR_CLUSTER,
            star.id,
            star.x,
            star.y,
            _star_cluster_disk_radius(star),
            qx,
            qy,
            radius_ly,
        )
        if hit is not None:
            hits.append(hit)
    for hole in turn.blackholes:
        hit = _disk_hit(
            KIND_BLACK_HOLE,
            hole.id,
            hole.x,
            hole.y,
            float(ergosphere_outer_radius(hole.coreradius, hole.bandradius)),
            qx,
            qy,
            radius_ly,
        )
        if hit is not None:
            hits.append(hit)
    hits.extend(_wormhole_hits(turn.wormholes, qx, qy, radius_ly))
    for planet in turn.planets:
        disk_radius = _debris_disk_radius(planet)
        if disk_radius is None:
            continue
        hit = _disk_hit(
            KIND_DEBRIS_DISK, planet.id, planet.x, planet.y, float(disk_radius), qx, qy, radius_ly
        )
        if hit is not None:
            hits.append(hit)
    return hits


def _star_cluster_disk_radius(star: Star) -> float:
    return max(float(star.radius), halo_radius_ly(star.mass))


def _debris_disk_radius(planet: Planet) -> int | None:
    """Seed planets carry border radius in ``debrisdisk`` (values > 1)."""
    if planet.debrisdisk <= 1:
        return None
    return planet.debrisdisk


def _wormhole_has_known_target(wormhole: Wormhole) -> bool:
    return not (wormhole.targetx == 0 and wormhole.targety == 0)


def _wormhole_hits(
    wormholes: list[Wormhole], qx: float, qy: float, radius_ly: float
) -> list[DiskProximityHit]:
    entrance_cells = {(wh.x, wh.y) for wh in wormholes}
    hits: list[DiskProximityHit] = []
    seen: set[tuple[int, int, int]] = set()
    for wormhole in wormholes:
        points = [(wormhole.x, wormhole.y)]
        target = (wormhole.targetx, wormhole.targety)
        if _wormhole_has_known_target(wormhole) and target not in entrance_cells:
            points.append(target)
        for px, py in points:
            key = (wormhole.id, px, py)
            if key in seen:
                continue
            seen.add(key)
            hit = _point_hit(KIND_WORMHOLE, wormhole.id, px, py, qx, qy, radius_ly)
            if hit is not None:
                hits.append(hit)
    return hits
