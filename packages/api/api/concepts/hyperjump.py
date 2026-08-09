"""Hyperjump (HYP) activation and landing estimate for map trails.

Nu: hyperdrive hull + FC ``HYP`` (case-insensitive) + warp > 0 + waypoint
distance > 20 ly + ≥50 kt neutronium. Landing is the waypoint when range is
340–360 ly; otherwise ~350 ly along the course toward the waypoint.
"""

from __future__ import annotations

import math

from api.concepts.hull_abilities import hull_has_hyperjump
from api.models.components import Hull
from api.models.ship import Ship

HYP_MIN_NEUTRONIUM = 50
HYP_MIN_WAYPOINT_LY = 20.0
HYP_FINE_TUNE_MIN_LY = 340.0
HYP_FINE_TUNE_MAX_LY = 360.0
HYP_FLAT_TRAVEL_LY = 350.0


def friendly_code_is_hyp(friendlycode: str) -> bool:
    """True when the friendly code is a case variant of ``HYP``."""
    return friendlycode.casefold() == "hyp"


def ship_is_performing_hyperjump(ship: Ship, hull: Hull | None) -> bool:
    """True when this ship is expected to hyperjump on the current turn."""
    if hull is None or not hull_has_hyperjump(hull):
        return False
    if not friendly_code_is_hyp(ship.friendlycode):
        return False
    if ship.warp <= 0:
        return False
    if ship.neutronium < HYP_MIN_NEUTRONIUM:
        return False
    dx = ship.targetx - ship.x
    dy = ship.targety - ship.y
    if dx == 0 and dy == 0:
        return False
    if math.hypot(float(dx), float(dy)) <= HYP_MIN_WAYPOINT_LY:
        return False
    return True


def hyperjump_landing_xy(ship: Ship) -> tuple[int, int]:
    """Estimated HYP landing coordinates (before post-jump warp-well pull).

    Caller must ensure the ship is performing a hyperjump (non-zero waypoint).
    """
    dx = float(ship.targetx - ship.x)
    dy = float(ship.targety - ship.y)
    distance = math.hypot(dx, dy)
    if distance <= 0.0:
        return (ship.x, ship.y)
    if HYP_FINE_TUNE_MIN_LY <= distance <= HYP_FINE_TUNE_MAX_LY:
        return (ship.targetx, ship.targety)
    scale = HYP_FLAT_TRAVEL_LY / distance
    return (
        int(round(ship.x + dx * scale)),
        int(round(ship.y + dy * scale)),
    )
