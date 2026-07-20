"""Host-aligned nebula density and visibility V(P) at a map cell.

Shared by Stellar Cartography ``sample_at`` tooltips and hybrid map-region coverage.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

# Host-aligned tooltip math (Planets.nu client / Meteor's Library).
NEBULA_VISIBILITY_NUMERATOR = 4000
NEBULA_VISIBILITY_MAX_LY = 250


class NebulaCenter(Protocol):
    """Minimal nebula center fields needed for density sampling."""

    id: int
    x: int
    y: int
    radius: int
    intensity: int


def distance_ly(x: float, y: float, fx: float, fy: float) -> float:
    """Euclidean distance in light-years between two map points."""
    return math.hypot(x - fx, y - fy)


def nebula_density_at(centers: Sequence[NebulaCenter], x: int, y: int) -> float:
    """Summed host density at integer map cell ``(x, y)``."""
    total = 0.0
    for center in centers:
        if center.radius <= 0 or center.id < 0:
            continue
        dist = distance_ly(x, y, center.x, center.y)
        if dist <= center.radius:
            total += math.ceil(center.intensity * (1.0 - dist / center.radius))
    return total


def nebula_visibility_ly(density: float) -> int | None:
    """Visibility range V(P) in ly from host density, or ``None`` outside fog."""
    if density <= 0:
        return None
    return min(
        NEBULA_VISIBILITY_MAX_LY,
        int(round(NEBULA_VISIBILITY_NUMERATOR / (density + 1))),
    )
