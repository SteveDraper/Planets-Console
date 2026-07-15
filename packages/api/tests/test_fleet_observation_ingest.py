"""Tests for fleet direct observation ingest."""

from __future__ import annotations

import copy
from dataclasses import replace

from api.analytics.fleet.chain import apply_fleet_turn_delta, ensure_fleet_baseline
from api.analytics.fleet.observation_ingest import ingest_turn_ship_observations
from api.analytics.fleet.scoreboard_counts import compute_max_ship_id_bound
from api.analytics.fleet.serialization import append_fleet_evidence_event
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetLastSeen,
    FleetPossiblyLost,
    FleetRowQualifiers,
    FleetShipRecord,
    FleetShipRecordFields,
)

from tests.fleet_fixtures import ledger_for_player, single_ship_turn


def test_new_sighting_creates_observed_ship_row():
    turn = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    snapshot = ensure_fleet_baseline(628580, 1, turn)

    result = ingest_turn_ship_observations(snapshot, turn)

    ledger = ledger_for_player(result, 8)
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.disposition == "active"
    assert record.fields.ship_id == FleetFieldKnown(value=42)
    assert record.fields.hull == FleetFieldKnown(value=13)
    assert record.last_seen is not None
    assert record.last_seen.turn == 1
    assert record.last_seen.x == 1000
    assert record.last_seen.y == 2000
    assert len(record.events) == 1
    assert record.events[0].kind == "sighting"
    assert record.events[0].source == "turnInfo.ships"
    assert record.events[0].payload["shipId"] == 42
    assert record.events[0].payload["beamCount"] == 8
    assert record.events[0].payload["launcherCount"] == 6
    assert record.build_option_sets == [
        FleetBuildOptionSet(
            hull_id=13,
            engine_id=9,
            beam_id=3,
            torp_id=6,
            beam_count=8,
            launcher_count=6,
        )
    ]
    assert record.display_default_option_set_index == 0


def test_repeat_sighting_refreshes_confirmed_build_option_set():
    turn_one = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    snapshot = ingest_turn_ship_observations(ensure_fleet_baseline(628580, 1, turn_one), turn_one)
    record = ledger_for_player(snapshot, 8).records[0]
    record.build_option_sets = [
        FleetBuildOptionSet(label="stale inferred", beam_count=1, launcher_count=1),
        FleetBuildOptionSet(label="alternate", beam_count=2, launcher_count=2),
    ]
    record.display_default_option_set_index = 1

    turn_two = single_ship_turn(turn_number=2, ship_id=42, owner_id=8, x=1100, y=2100)
    turn_two = replace(
        turn_two,
        scores=[replace(score, turn=2) for score in turn_two.scores],
    )
    result = ingest_turn_ship_observations(snapshot, turn_two)

    refreshed = ledger_for_player(result, 8).records[0]
    assert refreshed.build_option_sets == [
        FleetBuildOptionSet(
            hull_id=13,
            engine_id=9,
            beam_id=3,
            torp_id=6,
            beam_count=8,
            launcher_count=6,
        )
    ]
    assert refreshed.display_default_option_set_index == 0


def test_repeat_sighting_appends_events_and_updates_position():
    turn_one = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    snapshot = ingest_turn_ship_observations(ensure_fleet_baseline(628580, 1, turn_one), turn_one)
    record_id = ledger_for_player(snapshot, 8).records[0].record_id

    turn_two = single_ship_turn(turn_number=2, ship_id=42, owner_id=8, x=1100, y=2100)
    turn_two = replace(
        turn_two,
        scores=[replace(score, turn=2) for score in turn_two.scores],
    )
    result = ingest_turn_ship_observations(snapshot, turn_two)

    record = ledger_for_player(result, 8).records[0]
    assert record.record_id == record_id
    assert [event.kind for event in record.events] == ["sighting", "position_update"]
    assert record.last_seen is not None
    assert record.last_seen.turn == 2
    assert record.last_seen.x == 1100


def test_events_are_append_only():
    turn = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    first_event = FleetEvidenceEvent(
        event_id="evt-prior",
        kind="scoreboard_delta",
        turn=1,
        source="scoreboard",
        payload={"warshipDelta": -1},
    )
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="seed-rec",
            fields=FleetShipRecordFields(ship_id=FleetFieldKnown(value=42)),
            last_seen=FleetLastSeen(turn=0, x=1000, y=2000),
            events=[first_event],
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    record = next(
        rec for rec in ledger_for_player(result, 8).records if rec.record_id == "seed-rec"
    )
    assert record.events[0] == first_event
    assert record.events[-1].kind == "sighting"
    assert len(record.events) == 2


def test_turn_one_sightings_seed_ledger_without_game_start_inventory():
    turn = single_ship_turn(turn_number=1, ship_id=7, owner_id=8, x=500, y=600)
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
    )

    ledger = ledger_for_player(snapshot, 8)
    assert len(ledger.records) == 1
    assert ledger.records[0].fields.ship_id == FleetFieldKnown(value=7)


def test_id_bound_skipped_when_scores_missing():
    current_turn = single_ship_turn(turn_number=2, ship_id=2, owner_id=8, x=200, y=200)
    current_turn = replace(current_turn, scores=[])
    snapshot = ensure_fleet_baseline(628580, 1, current_turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="inferred-placeholder",
            fields=FleetShipRecordFields(ship_id=FleetFieldUnknown()),
        )
    )

    result = ingest_turn_ship_observations(snapshot, current_turn)

    placeholder = next(
        rec
        for rec in ledger_for_player(result, 8).records
        if rec.record_id == "inferred-placeholder"
    )
    assert placeholder.fields.ship_id == FleetFieldUnknown()
    assert not any(event.kind == "id_bound_tightened" for event in placeholder.events)
    assert compute_max_ship_id_bound(current_turn) is None


def test_id_bound_tightens_for_unmatched_rows_when_counts_known():
    current_turn = single_ship_turn(turn_number=2, ship_id=2, owner_id=8, x=200, y=200)
    score = replace(
        current_turn.scores[0],
        turn=2,
        ownerid=8,
        capitalships=1,
        freighters=0,
        shipchange=0,
        freighterchange=0,
    )
    current_turn = replace(current_turn, scores=[score])
    snapshot = ensure_fleet_baseline(628580, 1, current_turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="inferred-placeholder",
            fields=FleetShipRecordFields(ship_id=FleetFieldUnknown()),
            events=[
                FleetEvidenceEvent(
                    event_id="evt-placeholder",
                    kind="scoreboard_delta",
                    turn=2,
                    source="scoreboard",
                    payload={"shipClass": "warship", "warshipDelta": 1, "freighterDelta": 0},
                )
            ],
        )
    )

    result = ingest_turn_ship_observations(snapshot, current_turn)

    placeholder = next(
        rec
        for rec in ledger_for_player(result, 8).records
        if rec.record_id == "inferred-placeholder"
    )
    assert placeholder.fields.ship_id == FleetFieldBounded(operator="lte", value=1)
    assert placeholder.events[-1].kind == "id_bound_tightened"


def test_bounded_placeholder_absorbs_matching_sighting():
    current_turn = single_ship_turn(turn_number=2, ship_id=3, owner_id=8, x=200, y=200)
    snapshot = ensure_fleet_baseline(628580, 1, current_turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="bounded-placeholder",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=5),
            ),
            last_seen=FleetLastSeen(turn=1, x=200, y=200),
        )
    )

    result = ingest_turn_ship_observations(snapshot, current_turn)

    ledger = ledger_for_player(result, 8)
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.record_id == "bounded-placeholder"
    assert record.fields.ship_id == FleetFieldKnown(value=3)
    assert record.events[-1].kind == "sighting"
    assert record.events[-1].payload["shipId"] == 3


def test_compute_max_ship_id_bound_uses_scoreboard_totals(sample_turn):
    bound = compute_max_ship_id_bound(sample_turn)
    turn_number = sample_turn.settings.turn
    current_scores = [score for score in sample_turn.scores if score.turn == turn_number]
    total = sum(score.capitalships + score.freighters for score in current_scores)
    net = sum(score.shipchange + score.freighterchange for score in current_scores)
    builds = sum(
        max(0, score.shipchange) + max(0, score.freighterchange) for score in current_scores
    )
    assert bound == total - net + builds


def test_alibi_applies_after_recorded_count_decrease_and_later_sighting():
    turn_one = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    snapshot = ingest_turn_ship_observations(ensure_fleet_baseline(628580, 1, turn_one), turn_one)
    record = ledger_for_player(snapshot, 8).records[0]
    record.qualifiers = FleetRowQualifiers(
        possibly_lost=FleetPossiblyLost(since_turn=5, source="scoreboard"),
    )

    turn_six = single_ship_turn(turn_number=6, ship_id=42, owner_id=8, x=1000, y=2000)
    result = ingest_turn_ship_observations(snapshot, turn_six)

    updated = ledger_for_player(result, 8).records[0]
    assert updated.qualifiers.alibi is not None
    assert updated.qualifiers.alibi.after_turn == 5
    assert updated.qualifiers.alibi.sighting_turn == 6
    assert any(event.kind == "alibi" for event in updated.events)


def test_killed_ships_are_ignored():
    turn = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    killed_ship = copy.deepcopy(turn.ships[0])
    killed_ship = replace(killed_ship, turnkilled=1)
    turn = replace(turn, ships=[killed_ship])

    result = ingest_turn_ship_observations(ensure_fleet_baseline(628580, 1, turn), turn)

    assert ledger_for_player(result, 8).records == []


def test_alibi_from_scoreboard_delta_event_on_record():
    turn_five = single_ship_turn(turn_number=5, ship_id=42, owner_id=8, x=1000, y=2000)
    snapshot = ensure_fleet_baseline(628580, 1, turn_five)
    record = FleetShipRecord(
        record_id="tracked",
        fields=FleetShipRecordFields(ship_id=FleetFieldKnown(value=42)),
    )
    append_fleet_evidence_event(
        record,
        FleetEvidenceEvent(
            event_id="evt-decrease",
            kind="scoreboard_delta",
            turn=4,
            source="scoreboard",
            payload={"warshipDelta": -1, "freighterDelta": 0},
        ),
    )
    snapshot.players[0].records.append(record)

    result = ingest_turn_ship_observations(snapshot, turn_five)

    updated = next(
        rec for rec in ledger_for_player(result, 8).records if rec.record_id == "tracked"
    )
    assert updated.qualifiers.alibi is not None
    assert updated.qualifiers.alibi.after_turn == 4


def test_alibi_uses_latest_scoreboard_decrease_before_sighting():
    turn_six = single_ship_turn(turn_number=6, ship_id=42, owner_id=8, x=1000, y=2000)
    snapshot = ensure_fleet_baseline(628580, 1, turn_six)
    record = FleetShipRecord(
        record_id="tracked",
        fields=FleetShipRecordFields(ship_id=FleetFieldKnown(value=42)),
    )
    for turn, event_id in ((3, "evt-decrease-3"), (5, "evt-decrease-5")):
        append_fleet_evidence_event(
            record,
            FleetEvidenceEvent(
                event_id=event_id,
                kind="scoreboard_delta",
                turn=turn,
                source="scoreboard",
                payload={"warshipDelta": -1, "freighterDelta": 0},
            ),
        )
    snapshot.players[0].records.append(record)

    result = ingest_turn_ship_observations(snapshot, turn_six)

    updated = next(
        rec for rec in ledger_for_player(result, 8).records if rec.record_id == "tracked"
    )
    assert updated.qualifiers.alibi is not None
    assert updated.qualifiers.alibi.after_turn == 5
    assert updated.qualifiers.alibi.sighting_turn == 6
