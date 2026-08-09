"""Wire-only fleet ship heading/speed for map heading trails.

Not persisted on the durable ledger. Resolves motion from the current-turn
``TurnInfo.ships`` row matching a known ship id (typically a direct sighting).
"""

from __future__ import annotations

import math

from api.analytics.fleet.field_constraints import known_ship_id_value
from api.analytics.fleet.types import FleetShipRecord
from api.concepts.hull_abilities import hull_has_gravitonic_movement
from api.concepts.planet_connections.wells import max_travel_distance
from api.concepts.turn_component_catalog import hulls_by_id
from api.concepts.warp_well import WarpWellKind, coordinate_in_warp_well
from api.models.game import TurnInfo
from api.models.planet import Planet
from api.models.ship import Ship

# Nu/host sentinel: heading unset when the ship is not on a course.
_UNKNOWN_HEADING = -1


def fleet_ship_motion_wire(
    record: FleetShipRecord,
    *,
    turn: TurnInfo,
) -> dict[str, object] | None:
    """Return SPA motion payload for one record, or None when not underway.

    Attached only when the record has a known ship id present in ``turn.ships``
    that is underway (``targetx``/``targety`` ≠ position) with usable warp and a
    resolvable heading (direct ``heading`` or derived from the waypoint).
    Includes gravitonic ×2 in ``travelLyPerTurn``. ``trailStop`` is always set
    (waypoint, or planet when the waypoint is on/in a normal warp well).
    """
    ship_id = known_ship_id_value(record)
    if ship_id is None:
        return None
    ship = _ship_by_id(turn, ship_id)
    if ship is None:
        return None
    if ship.warp < 1:
        return None
    if ship.targetx == ship.x and ship.targety == ship.y:
        return None

    heading = _resolve_heading_degrees(ship)
    if heading is None:
        return None

    gravitonic = _ship_has_gravitonic_movement(ship, turn=turn)
    travel_ly = max_travel_distance(ship.warp, gravitonic)
    stop_x, stop_y = _resolve_trail_stop(ship, turn.planets)

    return {
        "heading": heading,
        "warp": ship.warp,
        "travelLyPerTurn": travel_ly,
        "trailStop": {"x": stop_x, "y": stop_y},
    }


def _ship_by_id(turn: TurnInfo, ship_id: int) -> Ship | None:
    for ship in turn.ships:
        if ship.id == ship_id:
            return ship
    return None


def _ship_has_gravitonic_movement(ship: Ship, *, turn: TurnInfo) -> bool:
    hull = hulls_by_id(turn).get(ship.hullid)
    if hull is None:
        return False
    return hull_has_gravitonic_movement(hull)


def _resolve_heading_degrees(ship: Ship) -> int | None:
    """Heading in degrees (0 = north, clockwise). None when unknown."""
    if ship.heading != _UNKNOWN_HEADING and ship.heading >= 0:
        return int(ship.heading) % 360

    dx = ship.targetx - ship.x
    dy = ship.targety - ship.y
    if dx == 0 and dy == 0:
        return None
    # Match SPA ion-storm convention: 0 north, positive clockwise (atan2(dx, dy)).
    degrees = math.degrees(math.atan2(float(dx), float(dy)))
    if degrees < 0.0:
        degrees += 360.0
    return int(round(degrees)) % 360


def _resolve_trail_stop(
    ship: Ship,
    planets: list[Planet],
) -> tuple[int, int]:
    """Waypoint clamp for forward trail extension. Caller ensures ship is underway."""
    planet_stop = _planet_stop_for_waypoint(ship.targetx, ship.targety, planets)
    if planet_stop is not None:
        return planet_stop
    return (ship.targetx, ship.targety)


def _planet_stop_for_waypoint(
    waypoint_x: int,
    waypoint_y: int,
    planets: list[Planet],
) -> tuple[int, int] | None:
    """Planet orbit when the waypoint is on the planet or inside its normal warp well."""
    for planet in planets:
        if waypoint_x == planet.x and waypoint_y == planet.y:
            return (planet.x, planet.y)
        if coordinate_in_warp_well(
            planet,
            float(waypoint_x),
            float(waypoint_y),
            WarpWellKind.NORMAL,
        ):
            return (planet.x, planet.y)
    return None
