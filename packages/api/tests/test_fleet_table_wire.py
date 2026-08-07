"""Tests for SPA fleet table wire shaping."""

from __future__ import annotations

from api.analytics.fleet.chain import ensure_fleet_baseline
from api.analytics.fleet.fleet_table_player_run import wire_cached_player_events
from api.analytics.fleet.military_estimate import fleet_ship_military_estimate_2x
from api.analytics.fleet.serialization import fleet_ship_record_to_json
from api.analytics.fleet.table_wire import (
    fleet_acquisition_ledger_to_table_wire,
    fleet_ship_record_to_table_wire,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    FleetShipRecord,
    PersistedFleetLedger,
)


def test_table_wire_record_omits_evidence_events(sample_turn):
    record = FleetShipRecord(
        record_id="rec-1",
        disposition="active",
        events=(),
    )
    core_record = fleet_ship_record_to_json(record)
    assert core_record["events"] == []

    table_record = fleet_ship_record_to_table_wire(record, turn=sample_turn)
    assert "events" not in table_record
    assert table_record["recordId"] == "rec-1"


def test_table_wire_ledger_matches_bff_player_shape(sample_turn):
    baseline = ensure_fleet_baseline(628580, 1, sample_turn)
    ledger = baseline.players[0]
    table_wire = fleet_acquisition_ledger_to_table_wire(ledger, turn=sample_turn)
    assert table_wire["playerId"] == ledger.player_id
    assert len(table_wire["records"]) == len(ledger.records)
    for record in table_wire["records"]:
        assert "events" not in record


def test_table_wire_omits_events_and_estimate_when_not_estimable(sample_turn):
    record = FleetShipRecord(
        record_id="rec-minimal",
        disposition="active",
        events=(),
    )
    table_record = fleet_ship_record_to_table_wire(record, turn=sample_turn)
    assert table_record["recordId"] == "rec-minimal"
    assert table_record["disposition"] == "active"
    assert "events" not in table_record
    assert "militaryEstimate2x" not in table_record

    ledger = FleetAcquisitionLedger(
        player_id=1,
        player_name="minimal",
        records=[record],
    )
    table_ledger = fleet_acquisition_ledger_to_table_wire(ledger, turn=sample_turn)
    assert len(table_ledger["records"]) == 1
    assert table_ledger["records"][0]["recordId"] == "rec-minimal"
    assert "events" not in table_ledger["records"][0]
    assert "militaryEstimate2x" not in table_ledger["records"][0]


def test_cached_stream_events_use_table_wire(sample_turn):
    baseline = ensure_fleet_baseline(628580, 1, sample_turn)
    ledger = baseline.players[0]
    persisted = PersistedFleetLedger(
        ledger=ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    events = wire_cached_player_events(persisted, turn=sample_turn)
    ledger_event = events[0]
    assert ledger_event["type"] == "ledger_updated"
    ledger_wire = ledger_event["ledger"]
    assert isinstance(ledger_wire, dict)
    for record in ledger_wire.get("records", []):
        assert isinstance(record, dict)
        assert "events" not in record
        domain = next(r for r in ledger.records if r.record_id == record["recordId"])
        estimate = fleet_ship_military_estimate_2x(domain, turn=sample_turn)
        if estimate is None:
            assert "militaryEstimate2x" not in record
        else:
            assert record["militaryEstimate2x"] == estimate
