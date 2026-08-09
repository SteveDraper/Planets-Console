"""Wire-only fleet ship heading/speed for map heading trails.

Not persisted on the durable ledger. Resolves motion from the current-turn
``TurnInfo.ships`` row matching a known ship id (typically a direct sighting).
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from api.analytics.fleet.field_constraints import known_ship_id_value
from api.analytics.fleet.types import FleetShipRecord
from api.concepts.hull_abilities import hull_has_gravitonic_movement
from api.concepts.planet_connections.wells import max_travel_distance
from api.concepts.turn_component_catalog import TurnComponentIndexes, turn_component_indexes
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
    ships_by_id: Mapping[int, Ship] | None = None,
    catalog: TurnComponentIndexes | None = None,
) -> dict[str, object] | None:
    """Return SPA motion payload for one record, or None when not underway.

    Attached only when the record has a known ship id present in ``turn.ships``
    that is underway (``targetx``/``targety`` ≠ position) with warp in 1..9 and a
    resolvable heading (direct ``heading`` or derived from the waypoint).
    Includes gravitonic ×2 in ``travelLyPerTurn``. ``trailStop`` is always set
    (waypoint, or planet when warp >= 2 and the waypoint is on/in a normal warp
    well -- W1 is not pulled into wells, so trailStop stays at the waypoint).

    Optional ``ships_by_id`` / ``catalog`` avoid rebuilding indexes when the
    caller already has them (e.g. ledger table-wire shaping).
    """
    ship_id = known_ship_id_value(record)
    if ship_id is None:
        return None
    ship_index = ships_by_id if ships_by_id is not None else _ships_by_id(turn)
    ship = ship_index.get(ship_id)
    if ship is None:
        return None
    if not 1 <= ship.warp <= 9:
        return None
    if ship.targetx == ship.x and ship.targety == ship.y:
        return None

    heading = _resolve_heading_degrees(ship)
    if heading is None:
        return None

    indexes = catalog if catalog is not None else turn_component_indexes(turn)
    gravitonic = _ship_has_gravitonic_movement(ship, catalog=indexes)
    travel_ly = max_travel_distance(ship.warp, gravitonic)
    stop_x, stop_y = _resolve_trail_stop(ship, turn.planets)

    return {
        "heading": heading,
        "warp": ship.warp,
        "travelLyPerTurn": travel_ly,
        "trailStop": {"x": stop_x, "y": stop_y},
    }


def _ships_by_id(turn: TurnInfo) -> dict[int, Ship]:
    return {ship.id: ship for ship in turn.ships}


def _ship_has_gravitonic_movement(
    ship: Ship,
    *,
    catalog: TurnComponentIndexes,
) -> bool:
    hull = catalog.hulls_by_id.get(ship.hullid)
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
    """Waypoint clamp for forward trail extension. Caller ensures ship is underway.

    Host warp wells pull ships ending within 3 ly unless non-moving or W1.
    Only snap to planet for warp >= 2; W1 keeps the raw waypoint.
    """
    if ship.warp >= 2:
        planet_stop = _planet_stop_for_waypoint(ship.targetx, ship.targety, planets)
        if planet_stop is not None:
            return planet_stop
    return (ship.targetx, ship.targety)


def _planet_stop_for_waypoint(
    waypoint_x: int,
    waypoint_y: int,
    planets: list[Planet],
) -> tuple[int, int] | None:
    """Planet orbit when the waypoint is on the planet or inside its normal warp well.

    Caller gates on warp >= 2 (W1 is not pulled into wells).
    """
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
