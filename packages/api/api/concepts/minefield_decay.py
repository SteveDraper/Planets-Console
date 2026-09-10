"""Minefield radius and per-turn decay (default 5% or nebula 15%)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from api.concepts.stellar_cartography.nebula_visibility import distance_ly

DEFAULT_MINEFIELD_DECAY_KEEP_FRACTION = 0.95
NEBULA_MINEFIELD_DECAY_KEEP_FRACTION = 0.85


class NebulaDisk(Protocol):
    """Minimal nebula fields for minefield decay overlap."""

    id: int
    x: int
    y: int
    radius: int


def radius_from_units(units: int) -> int:
    """Pre- or post-decay radius in ly: ``floor(sqrt(units))``."""
    if units <= 0:
        return 0
    return math.isqrt(units)


def remaining_units_after_decay(units: int, keep_fraction: float) -> int:
    """Mines remaining in one field after one turn at ``keep_fraction``."""
    if units <= 0:
        return 0
    return max(0, round(units * keep_fraction) - 1)


def remaining_units_after_default_decay(units: int) -> int:
    """Mines remaining in one field after one turn of default decay."""
    return remaining_units_after_decay(units, DEFAULT_MINEFIELD_DECAY_KEEP_FRACTION)


def remaining_units_after_nebula_decay(units: int) -> int:
    """Mines remaining in one field after one turn of nebula-accelerated decay."""
    return remaining_units_after_decay(units, NEBULA_MINEFIELD_DECAY_KEEP_FRACTION)


def lost_units_after_default_decay(units: int) -> int:
    """Units destroyed in one field by one turn of default decay."""
    if units <= 0:
        return 0
    return units - remaining_units_after_default_decay(units)


def equal_split_field_units(total_units: int, field_count: int) -> tuple[int, ...]:
    """Split ``total_units`` across ``field_count`` fields as evenly as possible.

    Remainder units go to the first fields. Non-positive ``field_count`` or
    ``total_units`` yield no fields.
    """
    if field_count <= 0 or total_units <= 0:
        return ()
    base, remainder = divmod(total_units, field_count)
    return tuple(base + 1 if index < remainder else base for index in range(field_count))


def minefield_intersects_nebula(
    field_x: int,
    field_y: int,
    pre_radius: int,
    nebula: NebulaDisk,
) -> bool:
    """True when the pre-decay minefield disk intersects a usable nebula disk."""
    if nebula.id < 0 or nebula.radius <= 0:
        return False
    return distance_ly(field_x, field_y, nebula.x, nebula.y) <= pre_radius + nebula.radius


def minefield_intersects_any_nebula(
    field_x: int,
    field_y: int,
    pre_radius: int,
    nebulas: Sequence[NebulaDisk],
) -> bool:
    """True when the pre-decay disk intersects any usable nebula (no stacking)."""
    return any(
        minefield_intersects_nebula(field_x, field_y, pre_radius, nebula) for nebula in nebulas
    )


def remaining_units_after_known_decay(
    units: int,
    field_x: int,
    field_y: int,
    nebulas: Sequence[NebulaDisk],
) -> int:
    """Remaining units after one turn, using nebula keep-fraction iff disks overlap."""
    if units <= 0:
        return 0
    pre_radius = radius_from_units(units)
    if minefield_intersects_any_nebula(field_x, field_y, pre_radius, nebulas):
        return remaining_units_after_nebula_decay(units)
    return remaining_units_after_default_decay(units)
