"""Hull classification helpers shared across analytics.

Freighter vs military is defined by weapon *slots* on the hull catalog entry,
not by currently fitted loadout.
"""

from __future__ import annotations

from api.models.components import Hull

# Solver / fleet sentinel: not a host hull id. Means "some freighter hull"
# (no weapon slots). Preserved on fleet build option sets as hullId 0.
GENERIC_FREIGHTER_SENTINEL_HULL_ID = 0


def is_generic_freighter_sentinel_hull_id(hull_id: int | None) -> bool:
    return hull_id == GENERIC_FREIGHTER_SENTINEL_HULL_ID


def hull_has_weapon_slots(hull: Hull) -> bool:
    """True when the hull can mount beams, torpedo tubes, or fighter bays."""
    return hull.beams > 0 or hull.launchers > 0 or hull.fighterbays > 0


def hull_is_freighter(hull: Hull) -> bool:
    """True when the hull has no weapon slots (Planets.nu freighter class)."""
    return not hull_has_weapon_slots(hull)
