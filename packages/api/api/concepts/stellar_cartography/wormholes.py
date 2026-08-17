"""Wormhole destination knowledge on the map plane."""

from __future__ import annotations

from api.models.space import Wormhole


def wormhole_has_known_target(wormhole: Wormhole) -> bool:
    """True when the host reports a destination other than the unknown sentinel ``(0, 0)``."""
    return not (wormhole.targetx == 0 and wormhole.targety == 0)
