"""FoW density credit for homeworld cluster constraint under incomplete charts.

Perspective ``rst.planets`` omits traditional planets outside planet-scan reach
(nebulae / reduced ``planetscanrange``). Known neighbor counts alone therefore
understate map-gen minima near scan-dark annulus. Credit expected planets in
unobserved very-close / close band area from a debiased chart density estimate.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from api.analytics.homeworld_locator.models import ClusterNeighborCounts
from api.concepts.homeworld_layout import (
    CLOSE_PLANETS_MAX_LY,
    MAP_SHAPE_IRREGULAR_ROUND,
    MAP_SHAPE_ROUND,
    VERY_CLOSE_PLANETS_MAX_LY,
)
from api.concepts.map_region_coverage import CoverageOrigin, point_covered_by_origins
from api.concepts.stellar_cartography.nebula_visibility import NebulaCenter, distance_ly
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import GameSettings
from api.models.planet import Planet

# Sample spacing for map-wide observed-fraction and per-candidate annulus area.
_MAP_SAMPLE_STEP_LY = 40.0
_ANNULUS_RADIAL_STEP_LY = 10.0
_ANNULUS_MIN_ANGLE_SAMPLES = 12


@dataclass(frozen=True)
class ClusterFowBandCredit:
    """Expected traditional-planet credit attributed to unobserved band area."""

    very_close: float
    close_band: float


def traditional_planets(planets: Sequence[Planet]) -> tuple[Planet, ...]:
    """Planets that participate in cluster density / neighbor counting."""
    return tuple(planet for planet in planets if not planet_is_planetoid(planet))


def max_traditional_planet_spacing_ly(planets: Sequence[Planet]) -> float:
    """Max pairwise Euclidean distance among traditional planets (0 if fewer than 2)."""
    bodies = traditional_planets(planets)
    if len(bodies) < 2:
        return 0.0
    best = 0.0
    for index, left in enumerate(bodies):
        for right in bodies[index + 1 :]:
            dist = distance_ly(left.x, left.y, right.x, right.y)
            if dist > best:
                best = dist
    return best


def is_round_map_shape(settings: GameSettings) -> bool:
    """True for round / irregular-round map shapes (not rectangular)."""
    return settings.mapshape in (MAP_SHAPE_ROUND, MAP_SHAPE_IRREGULAR_ROUND)


def populated_map_geometric_area_ly2(
    planets: Sequence[Planet],
    settings: GameSettings,
) -> float:
    """Geometric map area (ly²) used as the density denominator base.

    Round maps: circle area ``π * (D/2)²`` where ``D`` is max traditional planet
    spacing (populated-circle diameter). Rectangular maps: ``mapwidth * mapheight``.
    """
    if is_round_map_shape(settings):
        diameter = max_traditional_planet_spacing_ly(planets)
        if diameter > 0.0:
            radius = 0.5 * diameter
            return math.pi * radius * radius
    width = max(0, settings.mapwidth)
    height = max(0, settings.mapheight)
    return float(width * height)


def _sample_step_points(
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    step: float,
) -> list[tuple[float, float]]:
    if step <= 0.0 or x_max < x_min or y_max < y_min:
        return []
    points: list[tuple[float, float]] = []
    x = x_min
    while x <= x_max + 1e-9:
        y = y_min
        while y <= y_max + 1e-9:
            points.append((x, y))
            y += step
        x += step
    return points


def observed_area_fraction(
    *,
    planets: Sequence[Planet],
    settings: GameSettings,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    map_center: tuple[float, float],
) -> float:
    """Fraction of the geometric map area that is planet-scan observed.

    Round maps sample the populated circle of diameter ``D``; rectangular maps
    sample the ``mapwidth × mapheight`` rectangle anchored at the map center.
    Empty origins ⇒ fully unobserved (fraction 0).
    """
    if not origins:
        return 0.0

    geometric = populated_map_geometric_area_ly2(planets, settings)
    if geometric <= 0.0:
        return 0.0

    center_x, center_y = map_center
    if is_round_map_shape(settings):
        diameter = max_traditional_planet_spacing_ly(planets)
        if diameter <= 0.0:
            return 0.0
        radius = 0.5 * diameter
        samples = _sample_step_points(
            x_min=center_x - radius,
            x_max=center_x + radius,
            y_min=center_y - radius,
            y_max=center_y + radius,
            step=_MAP_SAMPLE_STEP_LY,
        )
        inside = [
            (x, y) for x, y in samples if distance_ly(x, y, center_x, center_y) <= radius + 1e-9
        ]
    else:
        inside = _sample_step_points(
            x_min=0.0,
            x_max=float(settings.mapwidth),
            y_min=0.0,
            y_max=float(settings.mapheight),
            step=_MAP_SAMPLE_STEP_LY,
        )

    if not inside:
        return 0.0
    covered = sum(1 for x, y in inside if point_covered_by_origins(x, y, origins, nebulas))
    return covered / len(inside)


def estimate_traditional_planet_density(
    planets: Sequence[Planet],
    settings: GameSettings,
    *,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    map_center: tuple[float, float],
) -> float:
    """Traditional planets per ly², debiased by observed-area fraction when possible.

    ``density = n_traditional / (geometric_area * observed_fraction)`` when the
    observed fraction is positive; otherwise ``n / geometric_area`` (no FoW
    debias). Planetoids are excluded from ``n``.
    """
    geometric = populated_map_geometric_area_ly2(planets, settings)
    if geometric <= 0.0:
        return 0.0
    count = len(traditional_planets(planets))
    if count == 0:
        return 0.0
    fraction = observed_area_fraction(
        planets=planets,
        settings=settings,
        origins=origins,
        nebulas=nebulas,
        map_center=map_center,
    )
    if fraction > 0.0:
        return count / (geometric * fraction)
    return count / geometric


def unobserved_annulus_area_ly2(
    candidate: Planet,
    *,
    r_inner: float,
    r_outer: float,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
) -> float:
    """Estimated unobserved area (ly²) in the closed outer / open inner annulus.

    Samples polar grid points; multiplies geometric annulus area by the
    unobserved sample fraction. Empty origins ⇒ fully unobserved.
    """
    if r_outer <= r_inner:
        return 0.0
    geometric = math.pi * (r_outer * r_outer - r_inner * r_inner)
    if geometric <= 0.0:
        return 0.0
    if not origins:
        return geometric

    span = 2.0 * math.pi
    angle_samples = max(
        _ANNULUS_MIN_ANGLE_SAMPLES,
        int(math.ceil(span / (math.pi / 36.0))),
    )
    radial_steps = max(1, int(math.ceil((r_outer - r_inner) / _ANNULUS_RADIAL_STEP_LY)))
    total = 0
    unobserved = 0
    for angle_index in range(angle_samples):
        angle = span * (angle_index / angle_samples)
        for radial_index in range(radial_steps + 1):
            radius = r_inner + (r_outer - r_inner) * (radial_index / radial_steps)
            # Exclude the exact inner boundary for the close band (r_inner > 0)
            # so samples sit in (r_inner, r_outer]; very-close uses r_inner=0.
            if r_inner > 0.0 and radius <= r_inner + 1e-9:
                continue
            if radius > r_outer + 1e-9:
                continue
            x = candidate.x + radius * math.cos(angle)
            y = candidate.y + radius * math.sin(angle)
            total += 1
            if not point_covered_by_origins(x, y, origins, nebulas):
                unobserved += 1
    if total == 0:
        return 0.0
    return geometric * (unobserved / total)


def cluster_band_fow_credit(
    candidate: Planet,
    *,
    density_per_ly2: float,
    origins: Sequence[CoverageOrigin],
    nebulas: Sequence[NebulaCenter],
    credit_multiplier: float = 1.0,
) -> ClusterFowBandCredit:
    """Raw FoW credit (before per-band deficit cap) for one candidate."""
    if density_per_ly2 <= 0.0 or credit_multiplier <= 0.0:
        return ClusterFowBandCredit(very_close=0.0, close_band=0.0)
    very_close_area = unobserved_annulus_area_ly2(
        candidate,
        r_inner=0.0,
        r_outer=VERY_CLOSE_PLANETS_MAX_LY,
        origins=origins,
        nebulas=nebulas,
    )
    close_area = unobserved_annulus_area_ly2(
        candidate,
        r_inner=VERY_CLOSE_PLANETS_MAX_LY,
        r_outer=CLOSE_PLANETS_MAX_LY,
        origins=origins,
        nebulas=nebulas,
    )
    return ClusterFowBandCredit(
        very_close=density_per_ly2 * very_close_area * credit_multiplier,
        close_band=density_per_ly2 * close_area * credit_multiplier,
    )


def capped_cluster_fow_credit(
    known: ClusterNeighborCounts,
    raw_credit: ClusterFowBandCredit,
    settings: GameSettings,
) -> ClusterFowBandCredit:
    """Cap each band's credit at the remaining map-gen deficit (no over-satisfaction)."""
    very_close_cap = max(0.0, float(settings.verycloseplanets) - float(known.very_close))
    close_cap = max(0.0, float(settings.closeplanets) - float(known.close_band))
    return ClusterFowBandCredit(
        very_close=min(raw_credit.very_close, very_close_cap),
        close_band=min(raw_credit.close_band, close_cap),
    )


def meets_homeworld_cluster_constraint_with_credit(
    known: ClusterNeighborCounts,
    credit: ClusterFowBandCredit,
    settings: GameSettings,
) -> bool:
    """True when known + capped FoW credit meets both neighborhood minima."""
    capped = capped_cluster_fow_credit(known, credit, settings)
    return (
        known.very_close + capped.very_close >= settings.verycloseplanets
        and known.close_band + capped.close_band >= settings.closeplanets
    )


def cluster_constraint_deficit_with_credit(
    known: ClusterNeighborCounts,
    credit: ClusterFowBandCredit,
    settings: GameSettings,
) -> int:
    """Non-negative integer deficit after applying capped FoW credit (0 = meets)."""
    capped = capped_cluster_fow_credit(known, credit, settings)
    very_close_deficit = max(
        0, math.ceil(settings.verycloseplanets - known.very_close - capped.very_close)
    )
    close_deficit = max(0, math.ceil(settings.closeplanets - known.close_band - capped.close_band))
    return very_close_deficit + close_deficit
