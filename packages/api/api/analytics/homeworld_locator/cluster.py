"""Homeworld cluster constraint scoring from map-gen neighborhood settings."""

from __future__ import annotations

from collections.abc import Sequence

from api.analytics.homeworld_locator.models import ClusterNeighborCounts
from api.concepts.homeworld_layout import CLOSE_PLANETS_MAX_LY, VERY_CLOSE_PLANETS_MAX_LY
from api.concepts.stellar_cartography.nebula_visibility import distance_ly
from api.concepts.warp_well import planet_is_planetoid
from api.models.game import GameSettings
from api.models.planet import Planet


def count_cluster_neighbors(
    candidate: Planet,
    planets: Sequence[Planet],
) -> ClusterNeighborCounts:
    """Count other traditional planets in the very-close and close neighborhood bands.

    Debris-disk **planetoids** (``debrisdisk == 1``) are excluded from both bands.
    """
    very_close = 0
    close_band = 0
    for planet in planets:
        if planet.id == candidate.id:
            continue
        if planet_is_planetoid(planet):
            continue
        dist = distance_ly(candidate.x, candidate.y, planet.x, planet.y)
        if dist <= VERY_CLOSE_PLANETS_MAX_LY:
            very_close += 1
        elif dist <= CLOSE_PLANETS_MAX_LY:
            close_band += 1
    return ClusterNeighborCounts(very_close=very_close, close_band=close_band)


def cluster_constraint_deficit(
    counts: ClusterNeighborCounts,
    settings: GameSettings,
) -> int:
    """Non-negative deficit vs ``verycloseplanets`` / ``closeplanets`` minima (0 = meets)."""
    very_close_deficit = max(0, settings.verycloseplanets - counts.very_close)
    close_deficit = max(0, settings.closeplanets - counts.close_band)
    return very_close_deficit + close_deficit


def meets_homeworld_cluster_constraint(
    counts: ClusterNeighborCounts,
    settings: GameSettings,
) -> bool:
    """True when neighbor counts meet both map-gen neighborhood minima."""
    return cluster_constraint_deficit(counts, settings) == 0
