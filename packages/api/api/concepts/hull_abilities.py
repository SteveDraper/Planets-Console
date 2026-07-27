"""Hull special-ability detectors from catalog ``Hull.special`` text.

Prefer substring checks on ``special`` over hard-coded hull ids so campaign
variants (e.g. Pawn B) stay covered when the host renames or forks hulls.
"""

from __future__ import annotations

from api.models.components import Hull


def hull_has_bioscan(hull: Hull) -> bool:
    """True when the hull runs Bioscan instead of Sensor Sweep."""
    return "bioscan" in hull.special.lower()


def hull_has_nebula_scanner(hull: Hull) -> bool:
    """True when the hull has the Nebula Scanner ability (100 ly floor)."""
    return "nebula scanner" in hull.special.lower()


def hull_has_gravitonic_movement(hull: Hull) -> bool:
    """True when the hull uses gravitonic accelerators (2x travel range)."""
    return "gravitonic" in hull.special.lower()
