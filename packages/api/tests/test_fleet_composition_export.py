"""Unit tests for fleet composition export materialization."""

from __future__ import annotations

from api.analytics.export_types import ExportScope
from api.analytics.fleet.composition_export import build_fleet_composition_branch
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
)

from tests.fleet_fixtures import single_ship_turn


def _composition_for_records(records, *, turn, player_id=8):
    snapshot = FleetTurnSnapshot(
        players=[FleetAcquisitionLedger(player_id=player_id, records=records)]
    )
    scope = ExportScope(
        game_id=628580,
        perspective=1,
        turn=turn.settings.turn,
        player_id=player_id,
    )
    return build_fleet_composition_branch(snapshot, scope, turn=turn)


def test_build_composition_omits_non_active_and_unknown_fields():
    turn = single_ship_turn(
        turn_number=1,
        ship_id=1,
        owner_id=8,
        x=100,
        y=100,
        hull_id=15,
        engine_id=3,
        beam_id=3,
        torpedoid=3,
    )
    composition = _composition_for_records(
        [
            FleetShipRecord(
                record_id="active",
                disposition="active",
                fields=FleetShipRecordFields(
                    hull=FleetFieldKnown(15),
                    engine=FleetFieldKnown(3),
                    beams=FleetFieldKnown(3),
                    launchers=FleetFieldKnown(3),
                ),
            ),
            FleetShipRecord(
                record_id="lost",
                disposition="lost",
                fields=FleetShipRecordFields(
                    hull=FleetFieldKnown(15),
                    launchers=FleetFieldKnown(3),
                ),
            ),
            FleetShipRecord(
                record_id="placeholder",
                disposition="active",
                fields=FleetShipRecordFields(
                    hull=FleetFieldUnknown(),
                    launchers=FleetFieldUnknown(),
                ),
            ),
        ],
        turn=turn,
    )
    assert composition["hullTypes"] == {"15": 1}
    assert composition["beamTypes"] == {"3": 1}
    assert composition["launcherTypes"] == {"3": 1}
    assert composition["maxTechLevel"] == {
        "hulls": 1,
        "engines": 3,
        "launchers": 3,
        "beams": 2,
    }


def test_build_composition_skips_unknown_catalog_ids_for_max_tech_level():
    turn = single_ship_turn(
        turn_number=1,
        ship_id=1,
        owner_id=8,
        x=100,
        y=100,
        hull_id=13,
        engine_id=9,
        beam_id=3,
        torpedoid=6,
    )
    composition = _composition_for_records(
        [
            FleetShipRecord(
                record_id="active",
                disposition="active",
                fields=FleetShipRecordFields(
                    hull=FleetFieldKnown(13),
                    engine=FleetFieldKnown(9),
                    beams=FleetFieldKnown(3),
                    launchers=FleetFieldKnown(6),
                ),
            ),
        ],
        turn=turn,
    )
    assert composition["hullTypes"] == {"13": 1}
    assert composition["launcherTypes"] == {"6": 1}
    assert composition["maxTechLevel"] == {"beams": 2}
