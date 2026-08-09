"""Tests for wire-only fleet ship heading/speed (map heading trails)."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.motion_wire import fleet_ship_motion_wire
from api.analytics.fleet.serialization import fleet_ship_record_to_json
from api.analytics.fleet.table_wire import fleet_ship_record_to_table_wire
from api.analytics.fleet.types import (
    FleetEvidenceEvent,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.concepts.planet_connections.wells import max_travel_distance
from api.models.game import TurnInfo
from api.models.ship import Ship


def _record_for_ship(ship_id: int | None) -> FleetShipRecord:
    fields = FleetShipRecordFields(
        ship_id=FleetFieldKnown(ship_id) if ship_id is not None else FleetFieldUnknown(),
    )
    return FleetShipRecord(
        record_id=f"rec-{ship_id if ship_id is not None else 'unknown'}",
        disposition="active",
        fields=fields,
        events=[
            FleetEvidenceEvent(
                event_id="evt-sight",
                kind="sighting",
                turn=1,
                source="test",
            )
        ],
    )


def _ship_with(sample_turn: TurnInfo, **changes) -> tuple[TurnInfo, Ship]:
    template = sample_turn.ships[0]
    ship = replace(template, **changes)
    turn = replace(sample_turn, ships=[ship])
    return turn, ship


def test_motion_omitted_without_known_ship_id(sample_turn):
    record = _record_for_ship(None)
    assert fleet_ship_motion_wire(record, turn=sample_turn) is None
    wire = fleet_ship_record_to_table_wire(record, turn=sample_turn)
    assert "motion" not in wire


def test_motion_omitted_when_ship_absent_from_turn(sample_turn):
    record = _record_for_ship(999_999)
    assert fleet_ship_motion_wire(record, turn=sample_turn) is None


def test_motion_omitted_when_warp_zero(sample_turn):
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=0,
        heading=90,
        targetx=sample_turn.ships[0].x + 10,
        targety=sample_turn.ships[0].y,
    )
    record = _record_for_ship(ship.id)
    assert fleet_ship_motion_wire(record, turn=turn) is None


def test_motion_omitted_when_warp_above_nine(sample_turn):
    """Warp outside Zod 1..9 must omit motion even when otherwise underway."""
    origin = sample_turn.ships[0]
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=10,
        heading=90,
        hullid=1,
        targetx=origin.x + 10,
        targety=origin.y,
    )
    record = _record_for_ship(ship.id)
    assert fleet_ship_motion_wire(record, turn=turn) is None


def test_motion_omitted_when_parked_even_with_unknown_heading(sample_turn):
    """Target equals position is not underway; residual/unknown heading does not emit."""
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=9,
        heading=-1,
        targetx=sample_turn.ships[0].x,
        targety=sample_turn.ships[0].y,
    )
    record = _record_for_ship(ship.id)
    assert fleet_ship_motion_wire(record, turn=turn) is None


def test_motion_uses_direct_heading_and_warp_square(sample_turn):
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=5,
        heading=90,
        hullid=1,
        targetx=sample_turn.ships[0].x + 40,
        targety=sample_turn.ships[0].y,
    )
    record = _record_for_ship(ship.id)
    motion = fleet_ship_motion_wire(record, turn=turn)
    assert motion == {
        "heading": 90,
        "warp": 5,
        "travelLyPerTurn": max_travel_distance(5, False),
        "trailStop": {"x": ship.targetx, "y": ship.targety},
    }


def test_motion_applies_gravitonic_multiplier(sample_turn):
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=9,
        heading=0,
        hullid=44,  # Br4 Class Gunship -- gravitonic in sample catalog
        targetx=sample_turn.ships[0].x,
        targety=sample_turn.ships[0].y + 100,
    )
    record = _record_for_ship(ship.id)
    motion = fleet_ship_motion_wire(record, turn=turn)
    assert motion is not None
    assert motion["travelLyPerTurn"] == max_travel_distance(9, True)
    assert motion["travelLyPerTurn"] == 162.0


def test_motion_derives_heading_from_waypoint_when_heading_unset(sample_turn):
    origin = sample_turn.ships[0]
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=3,
        heading=-1,
        hullid=1,
        targetx=origin.x + 30,
        targety=origin.y,
    )
    record = _record_for_ship(ship.id)
    motion = fleet_ship_motion_wire(record, turn=turn)
    assert motion is not None
    assert motion["heading"] == 90  # east
    assert motion["warp"] == 3
    assert motion["travelLyPerTurn"] == 9.0


def test_trail_stop_snaps_to_planet_when_waypoint_in_warp_well(sample_turn):
    planet = sample_turn.planets[0]
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=9,
        heading=45,
        hullid=1,
        x=planet.x + 50,
        y=planet.y,
        targetx=planet.x + 2,
        targety=planet.y,
    )
    record = _record_for_ship(ship.id)
    motion = fleet_ship_motion_wire(record, turn=turn)
    assert motion is not None
    assert motion["trailStop"] == {"x": planet.x, "y": planet.y}


def test_trail_stop_keeps_waypoint_for_w1_in_warp_well(sample_turn):
    """W1 is not pulled into wells -- trailStop stays at the raw waypoint."""
    planet = sample_turn.planets[0]
    waypoint_x = planet.x + 2
    waypoint_y = planet.y
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=1,
        heading=45,
        hullid=1,
        x=planet.x + 50,
        y=planet.y,
        targetx=waypoint_x,
        targety=waypoint_y,
    )
    record = _record_for_ship(ship.id)
    motion = fleet_ship_motion_wire(record, turn=turn)
    assert motion is not None
    assert motion["warp"] == 1
    assert motion["trailStop"] == {"x": waypoint_x, "y": waypoint_y}
    assert motion["trailStop"] != {"x": planet.x, "y": planet.y}


def test_motion_omitted_when_target_equals_position(sample_turn):
    """Parked ship with residual heading/warp is not underway -- no motion wire."""
    origin = sample_turn.ships[0]
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=9,
        heading=180,
        hullid=1,
        targetx=origin.x,
        targety=origin.y,
    )
    record = _record_for_ship(ship.id)
    assert fleet_ship_motion_wire(record, turn=turn) is None


def test_table_wire_attaches_motion_and_durable_omits(sample_turn):
    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=4,
        heading=270,
        hullid=1,
        targetx=sample_turn.ships[0].x - 20,
        targety=sample_turn.ships[0].y,
    )
    record = _record_for_ship(ship.id)
    durable = fleet_ship_record_to_json(record)
    assert "motion" not in durable

    wire = fleet_ship_record_to_table_wire(record, turn=turn)
    assert wire["motion"] == fleet_ship_motion_wire(record, turn=turn)


def test_motion_wire_accepts_precomputed_indexes(sample_turn):
    """Ledger path may pass ship/catalog indexes; payloads match turn-built defaults."""
    from api.concepts.turn_component_catalog import turn_component_indexes

    turn, ship = _ship_with(
        sample_turn,
        id=42,
        warp=9,
        heading=45,
        hullid=1,
        targetx=sample_turn.ships[0].x + 10,
        targety=sample_turn.ships[0].y,
    )
    record = _record_for_ship(ship.id)
    ships_by_id = {s.id: s for s in turn.ships}
    catalog = turn_component_indexes(turn)

    expected = fleet_ship_motion_wire(record, turn=turn)
    assert expected is not None
    assert (
        fleet_ship_motion_wire(
            record,
            turn=turn,
            ships_by_id=ships_by_id,
            catalog=catalog,
        )
        == expected
    )
    wire = fleet_ship_record_to_table_wire(
        record,
        turn=turn,
        ships_by_id=ships_by_id,
        catalog=catalog,
    )
    assert wire["motion"] == expected
