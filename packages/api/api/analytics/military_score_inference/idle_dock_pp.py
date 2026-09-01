"""Idle-dock priority-point equality for pre-limit PQ/PPQ rows.

``prioritypointchange == 2 * (starbases - ships built)`` when the observed
delta lies on that even lattice. Gift, trade, capture, and unmatched loss
contribute 0 PP. Classic PBP and PLS have no idle-dock constraint. Post-limit
spend is not this module.
"""

from __future__ import annotations

from typing import Protocol

from api.models.game import GameSettings


class IdleDockPpRow(Protocol):
    """Public scoreboard fields for idle-dock PP lattice and enforcement."""

    priority_point_delta: int
    starbases_owned: int
    planet_delta: int
    starbase_delta: int


def is_idle_dock_queue(settings: GameSettings) -> bool:
    """PQ or PPQ with a shared ship-limit (not Classic PBP, not PLS)."""
    if settings.shiplimittype != 0:
        return False
    return bool(settings.productionqueue or settings.planetaryproductionqueue)


def idle_dock_pp_on_lattice(row: IdleDockPpRow) -> bool:
    """True when observed PP is ``2 * (starbases - k)`` for integer k in ``[0, starbases]``."""
    starbases = row.starbases_owned
    priority_points = row.priority_point_delta
    if starbases < 0 or priority_points < 0 or priority_points % 2 != 0:
        return False
    idle_docks = priority_points // 2
    return idle_docks <= starbases


def should_enforce_idle_dock_pp(
    row: IdleDockPpRow,
    settings: GameSettings,
    *,
    is_after_ship_limit: bool,
) -> bool:
    """Lattice-gated idle-dock PP equality for public scoreboard fields."""
    if is_after_ship_limit:
        return False
    if not is_idle_dock_queue(settings):
        return False
    if row.planet_delta < 0 or row.starbase_delta < 0:
        return False
    return idle_dock_pp_on_lattice(row)


def idle_dock_implied_ships_built(row: IdleDockPpRow) -> int | None:
    """Ships built implied by idle-dock PP, or None when not on lattice."""
    if not idle_dock_pp_on_lattice(row):
        return None
    return row.starbases_owned - row.priority_point_delta // 2


IDLE_DOCK_PP_EQUALITY_LABEL = (
    "priorityPointChange == 2 * (starbasesOwned - shipsBuilt) (idle-dock PP equality)"
)
