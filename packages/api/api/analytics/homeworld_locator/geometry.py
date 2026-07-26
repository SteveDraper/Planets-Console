"""Circular + round homeworld candidate geometry (ring sites from map center)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from api.concepts.homeworld_layout import DEFAULT_MAP_CENTER_XY
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.concepts.warp_well import planet_is_planetoid
from api.models.planet import Planet

# How far a planet may sit from the ideal ring radius / expected sector point.
DEFAULT_RING_MATCH_TOLERANCE_LY = 40.0


def planet_cloud_center(planets: Sequence[Planet]) -> tuple[float, float] | None:
    """Axis-aligned bounding-box mid-point of planet positions, or ``None`` if too sparse."""
    if len(planets) < 2:
        return None
    xs = [planet.x for planet in planets]
    ys = [planet.y for planet in planets]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def resolve_map_center(
    planets: Sequence[Planet],
    *,
    fallback: tuple[float, float] = DEFAULT_MAP_CENTER_XY,
) -> tuple[float, float]:
    """Prefer planet-cloud bbox center; else classical Nu universe origin."""
    return planet_cloud_center(planets) or fallback


def find_circular_ring_homeworld_sites(
    planets: Sequence[Planet],
    *,
    center: tuple[float, float],
    player_count: int,
    pin: Planet,
    match_tolerance_ly: float = DEFAULT_RING_MATCH_TOLERANCE_LY,
) -> tuple[Planet, ...]:
    """Locate planets on the equal-angle ring fixed by ``pin``.

    Returns the pin plus nearest planets to the remaining sector points (unique ids).
    Requires ``player_count >= 1``. Does not assign rival slots -- callers treat
    non-pin sites as orphan homeworld candidates.
    """
    if player_count < 1:
        return ()
    center_x, center_y = center
    radius = distance_ly(pin.x, pin.y, center_x, center_y)
    if radius <= 0.0:
        return (pin,)

    pin_angle = math.atan2(pin.y - center_y, pin.x - center_x)
    sector = (2.0 * math.pi) / player_count
    chosen: dict[int, Planet] = {pin.id: pin}

    for step in range(1, player_count):
        angle = pin_angle + step * sector
        expected_x = center_x + radius * math.cos(angle)
        expected_y = center_y + radius * math.sin(angle)
        best: Planet | None = None
        best_dist = match_tolerance_ly
        for planet in planets:
            if planet.id in chosen:
                continue
            if planet_is_planetoid(planet):
                continue
            dist = distance_ly(planet.x, planet.y, expected_x, expected_y)
            if dist <= best_dist:
                best = planet
                best_dist = dist
        if best is not None:
            chosen[best.id] = best

    # Stable order: pin first, then remaining by increasing angle from pin.
    others = [planet for planet in chosen.values() if planet.id != pin.id]
    others.sort(
        key=lambda planet: (
            (math.atan2(planet.y - center_y, planet.x - center_x) - pin_angle) % (2.0 * math.pi)
        )
    )
    return (pin, *others)
