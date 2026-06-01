"""Black hole ergosphere geometry aligned with Planets.nu client ``getBlackHoleBand``."""

from __future__ import annotations

import math

# Planets.nu host constants; contract: test-fixtures/black-hole-ergosphere-contract.json.
ERGOSPHERE_BAND_COUNT = 9
BLACK_HOLE_HALO_EXTRA_LY = 5


def ergosphere_outer_radius(coreradius: int, bandradius: int) -> int:
    """Outer edge of the ergosphere in ly from the black hole center."""
    return coreradius + ERGOSPHERE_BAND_COUNT * bandradius


def black_hole_band_at(coreradius: int, bandradius: int, dist: float) -> int | None:
    """Return band index at ``dist`` ly from center, or ``None`` if outside the ergosphere.

    ``0`` is the lethal core. Bands ``1``..``9`` run inward-to-outward (1 = innermost).
    """
    if bandradius <= 0:
        return None
    outer = ergosphere_outer_radius(coreradius, bandradius)
    if dist > outer:
        return None
    if dist <= coreradius:
        return 0
    return min(
        ERGOSPHERE_BAND_COUNT,
        max(1, math.ceil((dist - coreradius) / bandradius)),
    )


def black_hole_max_warp_at(coreradius: int, bandradius: int, dist: float) -> int | None:
    """Max safe ordered warp at ``dist`` ly; ``None`` in core or outside ergosphere."""
    band = black_hole_band_at(coreradius, bandradius, dist)
    if band is None or band == 0:
        return None
    return band


def black_hole_fuel_saving_percent_at(coreradius: int, bandradius: int, dist: float) -> int | None:
    """Host predictor fuel bonus percent at ``dist`` ly; ``None`` in core or outside."""
    band = black_hole_band_at(coreradius, bandradius, dist)
    if band is None or band == 0:
        return None
    return 10 - band
