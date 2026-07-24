"""Tests for fleet analytic domain types and JSON codecs."""

from __future__ import annotations

import pytest
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.serialization import (
    append_fleet_evidence_event,
    fleet_acquisition_ledger_from_json,
    fleet_acquisition_ledger_to_json,
    fleet_build_option_set_from_json,
    fleet_build_option_set_to_json,
    fleet_count_discrepancy_from_json,
    fleet_count_discrepancy_to_json,
    fleet_evidence_event_to_json,
    fleet_field_constraint_from_json,
    fleet_field_constraint_to_json,
    fleet_materialization_provenance_from_json,
    fleet_materialization_provenance_to_json,
    fleet_ship_record_from_json,
    fleet_ship_record_to_json,
    fleet_turn_snapshot_from_json,
    fleet_turn_snapshot_to_json,
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetAlibi,
    FleetBuildOptionSet,
    FleetCountDiscrepancy,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldKnown,
    FleetFieldOptions,
    FleetFieldRegion,
    FleetFieldRegionStarbaseCoord,
    FleetFieldUnknown,
    FleetLastSeen,
    FleetMaterializationProvenance,
    FleetPossiblyLost,
    FleetRowQualifiers,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
    PersistedFleetLedger,
)
from api.errors import ValidationError


@pytest.mark.parametrize(
    ("constraint", "wire"),
    [
        (FleetFieldKnown(value=318), {"kind": "known", "value": 318}),
        (FleetFieldUnknown(), {"kind": "unknown"}),
        (
            FleetFieldBounded(operator="lte", value=318),
            {"kind": "bounded", "operator": "lte", "value": 318},
        ),
        (
            FleetFieldOptions(values=(9, 13)),
            {"kind": "options", "values": [9, 13]},
        ),
        (
            FleetFieldRegion(
                planet_ids=(101, 202),
                starbase_coords=(FleetFieldRegionStarbaseCoord(x=1000, y=2000),),
                overlay_id="sb-region-1",
            ),
            {
                "kind": "region",
                "planetIds": [101, 202],
                "starbaseCoords": [{"x": 1000, "y": 2000}],
                "overlayId": "sb-region-1",
            },
        ),
    ],
)
def test_fleet_field_constraint_round_trip(constraint, wire):
    assert fleet_field_constraint_to_json(constraint) == wire
    restored = fleet_field_constraint_from_json(wire)
    assert restored == constraint
    assert fleet_field_constraint_to_json(restored) == wire


def test_fleet_build_option_set_round_trip():
    option_set = FleetBuildOptionSet(
        combo_id="combo_13_9_3_6_8_6",
        label="Heavy Cruiser / Transwarp",
        solution_rank_weight=42,
        hull_id=13,
        engine_id=9,
        beam_id=3,
        torp_id=6,
        beam_count=8,
        launcher_count=6,
    )
    wire = fleet_build_option_set_to_json(option_set)
    restored = fleet_build_option_set_from_json(wire)
    assert restored == option_set
    assert fleet_build_option_set_to_json(restored) == wire


def test_fleet_build_option_set_round_trip_unknown_counts():
    option_set = FleetBuildOptionSet(
        hull_id=13,
        label="Fog hull only",
        beam_count=None,
        launcher_count=None,
    )
    wire = fleet_build_option_set_to_json(option_set)
    assert wire["beamCount"] is None
    assert wire["launcherCount"] is None
    restored = fleet_build_option_set_from_json(wire)
    assert restored == option_set
    assert fleet_build_option_set_to_json(restored) == wire


def test_fleet_ship_record_round_trip_with_qualifiers_and_fields():
    record = FleetShipRecord(
        record_id="rec-1",
        disposition="active",
        qualifiers=FleetRowQualifiers(
            possibly_lost=FleetPossiblyLost(since_turn=7, source="scoreboard"),
            alibi=FleetAlibi(after_turn=7, sighting_turn=9, source="turnInfo.ships"),
        ),
        fields=FleetShipRecordFields(
            ship_id=FleetFieldBounded(operator="lte", value=318),
            hull=FleetFieldKnown(value=13),
            engine=FleetFieldKnown(value=9),
            beams=FleetFieldOptions(values=(3, 5)),
            launchers=FleetFieldUnknown(),
            built_turn=FleetFieldKnown(value=4),
            location=FleetFieldRegion(planet_ids=(55,)),
        ),
        build_option_sets=[
            FleetBuildOptionSet(
                combo_id="combo_a",
                label="Option A",
                solution_rank_weight=10,
                hull_id=13,
                engine_id=9,
            ),
            FleetBuildOptionSet(
                combo_id="combo_b",
                label="Option B",
                solution_rank_weight=5,
                hull_id=1,
                engine_id=2,
            ),
        ],
        display_default_option_set_index=0,
        last_seen=FleetLastSeen(turn=9, x=1200, y=800, planet_id=55),
        events=[
            FleetEvidenceEvent(
                event_id="evt-1",
                kind="sighting",
                turn=9,
                source="turnInfo.ships",
                payload={"shipId": 301},
            )
        ],
    )

    wire = fleet_ship_record_to_json(record)
    restored = fleet_ship_record_from_json(wire)
    assert restored == record
    assert fleet_ship_record_to_json(restored) == wire


def test_append_fleet_evidence_event_appends_and_round_trips():
    record = FleetShipRecord(record_id="rec-2")
    first = FleetEvidenceEvent(
        event_id="evt-1",
        kind="scoreboard_delta",
        turn=3,
        source="scoreboard",
        payload={"warshipDelta": 1},
    )
    second = FleetEvidenceEvent(
        event_id="evt-2",
        kind="inference_update",
        turn=3,
        source="scores",
        payload={"solutionRankWeight": 12},
    )

    append_fleet_evidence_event(record, first)
    append_fleet_evidence_event(record, second)

    assert record.events == [first, second]

    wire = fleet_ship_record_to_json(record)
    restored = fleet_ship_record_from_json(wire)
    assert restored.events == [first, second]
    assert fleet_evidence_event_to_json(restored.events[1]) == fleet_evidence_event_to_json(second)


def test_fleet_count_discrepancy_round_trip():
    discrepancy = FleetCountDiscrepancy(
        host_turn=8,
        active_row_count=5,
        scoreboard_implied_count=4,
        report_refs=("report:host:8:player:2",),
    )
    wire = fleet_count_discrepancy_to_json(discrepancy)
    restored = fleet_count_discrepancy_from_json(wire)
    assert restored == discrepancy
    assert fleet_count_discrepancy_to_json(restored) == wire


def test_fleet_materialization_provenance_round_trip():
    provenance = FleetMaterializationProvenance(
        turn_evidence_at_n=True,
        prior_ledger_at_n_minus_1=False,
    )
    wire = fleet_materialization_provenance_to_json(provenance)
    restored = fleet_materialization_provenance_from_json(wire)
    assert restored == provenance
    assert restored.is_final is False


def test_persisted_fleet_ledger_round_trip():
    persisted = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=8, player_name="koshling"),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )
    wire = persisted_fleet_ledger_to_json(persisted)
    restored = persisted_fleet_ledger_from_json(wire)
    assert restored == persisted


def test_fleet_turn_snapshot_round_trip():
    snapshot = FleetTurnSnapshot(
        analytic_id="fleet",
        game_id=628580,
        perspective=1,
        turn=111,
        materialization_version=FLEET_MATERIALIZATION_VERSION,
        players=[
            FleetAcquisitionLedger(
                player_id=8,
                player_name="koshling",
                records=[
                    FleetShipRecord(
                        record_id="rec-1",
                        fields=FleetShipRecordFields(
                            ship_id=FleetFieldKnown(value=301),
                            hull=FleetFieldKnown(value=13),
                        ),
                    )
                ],
                discrepancy=FleetCountDiscrepancy(
                    host_turn=111,
                    active_row_count=2,
                    scoreboard_implied_count=1,
                ),
            )
        ],
    )

    wire = fleet_turn_snapshot_to_json(snapshot)
    restored = fleet_turn_snapshot_from_json(wire)
    assert restored == snapshot
    assert fleet_turn_snapshot_to_json(restored) == wire


def test_fleet_acquisition_ledger_round_trip():
    ledger = FleetAcquisitionLedger(
        player_id=3,
        player_name="player-3",
        records=[FleetShipRecord(record_id="rec-3")],
    )
    wire = fleet_acquisition_ledger_to_json(ledger)
    restored = fleet_acquisition_ledger_from_json(wire)
    assert restored == ledger
    assert fleet_acquisition_ledger_to_json(restored) == wire


def test_fleet_field_constraint_region_requires_locator():
    with pytest.raises(ValidationError, match="requires at least one locator"):
        fleet_field_constraint_from_json({"kind": "region"})


@pytest.mark.parametrize(
    ("from_json", "wire", "match"),
    [
        (
            fleet_field_constraint_from_json,
            {"kind": "bounded", "operator": "neq", "value": 1},
            "bounded operator is invalid",
        ),
        (
            fleet_field_constraint_from_json,
            {"kind": "options", "values": []},
            "requires non-empty values",
        ),
        (
            fleet_field_constraint_from_json,
            {"kind": "bogus"},
            "unknown fleet field constraint kind",
        ),
        (
            fleet_ship_record_from_json,
            {
                "recordId": "rec-1",
                "disposition": "active",
                "fields": {
                    "shipId": {"kind": "unknown"},
                    "hull": {"kind": "unknown"},
                    "engine": {"kind": "unknown"},
                    "beams": {"kind": "unknown"},
                    "launchers": {"kind": "unknown"},
                    "builtTurn": {"kind": "unknown"},
                    "location": {"kind": "unknown"},
                },
                "events": ["not-an-object"],
            },
            "fleet ship record events\\[0\\] must be an object",
        ),
        (
            fleet_ship_record_from_json,
            {
                "recordId": "rec-1",
                "disposition": "vanished",
                "fields": {
                    "shipId": {"kind": "unknown"},
                    "hull": {"kind": "unknown"},
                    "engine": {"kind": "unknown"},
                    "beams": {"kind": "unknown"},
                    "launchers": {"kind": "unknown"},
                    "builtTurn": {"kind": "unknown"},
                    "location": {"kind": "unknown"},
                },
            },
            "disposition is invalid",
        ),
        (
            fleet_ship_record_from_json,
            {
                "recordId": "rec-1",
                "disposition": "active",
                "fields": {
                    "shipId": {"kind": "unknown"},
                    "hull": {"kind": "unknown"},
                    "engine": {"kind": "unknown"},
                    "beams": {"kind": "unknown"},
                    "launchers": {"kind": "unknown"},
                    "builtTurn": {"kind": "unknown"},
                    "location": {"kind": "unknown"},
                },
                "buildOptionSets": [],
                "displayDefaultOptionSetIndex": 0,
            },
            "displayDefaultOptionSetIndex requires buildOptionSets",
        ),
        (
            fleet_acquisition_ledger_from_json,
            {"playerId": 1, "records": [42]},
            "fleet acquisition ledger records\\[0\\] must be an object",
        ),
        (
            fleet_turn_snapshot_from_json,
            {"analyticId": "fleet", "perspective": 1, "turn": 5, "players": []},
            "fleet turn snapshot gameId must be an int",
        ),
    ],
)
def test_fleet_deserialization_rejects_invalid_wire(from_json, wire, match):
    with pytest.raises(ValidationError, match=match):
        from_json(wire)


def test_fleet_evidence_event_rejects_invalid_kind():
    with pytest.raises(ValidationError, match="kind is invalid"):
        fleet_ship_record_from_json(
            {
                "recordId": "rec-1",
                "disposition": "active",
                "fields": {
                    "shipId": {"kind": "unknown"},
                    "hull": {"kind": "unknown"},
                    "engine": {"kind": "unknown"},
                    "beams": {"kind": "unknown"},
                    "launchers": {"kind": "unknown"},
                    "builtTurn": {"kind": "unknown"},
                    "location": {"kind": "unknown"},
                },
                "events": [
                    {
                        "eventId": "evt-1",
                        "kind": "sightng",
                        "turn": 1,
                        "source": "turnInfo.ships",
                    }
                ],
            }
        )


def test_fleet_ship_record_merged_disposition_round_trip():
    record = FleetShipRecord(
        record_id="rec-merged",
        disposition="merged",
        fields=FleetShipRecordFields(
            ship_id=FleetFieldKnown(value=101),
            hull=FleetFieldKnown(value=13),
        ),
    )
    wire = fleet_ship_record_to_json(record)
    restored = fleet_ship_record_from_json(wire)
    assert restored == record
    assert fleet_ship_record_to_json(restored) == wire


def test_fleet_count_collapse_event_round_trip():
    payload = {
        "peerRecordId": "absorbed-or-survivor-id",
        "shipId": 101,
        "shipClass": "warship",
        "constraintTightness": "bounded_lte",
        "tieBreak": "ship_id",
        "candidateSetSize": 4,
        "remainingSurplus": 3,
    }
    event = FleetEvidenceEvent(
        event_id="evt-collapse",
        kind="count_collapse",
        turn=9,
        source="fleet.count_collapse",
        payload=payload,
    )
    record = FleetShipRecord(
        record_id="rec-collapse",
        events=[event],
    )
    wire = fleet_ship_record_to_json(record)
    restored = fleet_ship_record_from_json(wire)
    assert restored.events == [event]
    assert fleet_evidence_event_to_json(restored.events[0]) == fleet_evidence_event_to_json(event)


def test_fleet_field_constraint_region_round_trip_overlay_only():
    constraint = FleetFieldRegion(overlay_id="sb-region-2")
    wire = fleet_field_constraint_to_json(constraint)
    assert wire == {"kind": "region", "overlayId": "sb-region-2"}
    restored = fleet_field_constraint_from_json(wire)
    assert restored == constraint
