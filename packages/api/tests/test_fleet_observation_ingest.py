"""Tests for fleet direct observation ingest."""

from __future__ import annotations

import copy
from dataclasses import replace

from api.analytics.fleet.chain import apply_fleet_turn_delta, ensure_fleet_baseline
from api.analytics.fleet.observation_ingest import (
    ingest_turn_ship_observations,
    record_has_direct_observation,
)
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
    # Full-information rematch replaces inferred alternates with the confirmed fit.
    snapshot = ingest_turn_ship_observations(ensure_fleet_baseline(628580, 8, turn_one), turn_one)
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
                hull=FleetFieldKnown(13),
                built_turn=FleetFieldKnown(1),
            ),
            build_option_sets=[
                FleetBuildOptionSet(
                    hull_id=13,
                    engine_id=9,
                    beam_id=3,
                    torp_id=6,
                    beam_count=8,
                    launcher_count=6,
                    solution_rank_weight=40,
                )
            ],
            last_seen=FleetLastSeen(turn=1, x=200, y=200),
        )
    )

    result = ingest_turn_ship_observations(snapshot, current_turn)

    ledger = ledger_for_player(result, 8)
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.record_id == "bounded-placeholder"
    assert record.fields.ship_id == FleetFieldKnown(value=3)
    assert [event.kind for event in record.events[-2:]] == ["option_set_match", "sighting"]
    match_event = record.events[-2]
    assert match_event.payload["shipId"] == 3
    assert match_event.payload["optionSetIndex"] == 0
    assert match_event.payload["solutionRankWeight"] == 40
    assert match_event.payload["tieBreak"] == "rank_weight"
    assert match_event.payload["candidateSetSize"] == 1
    assert record.events[-1].payload["shipId"] == 3


def test_exact_known_ship_id_skips_option_set_arbitration():
    turn = single_ship_turn(turn_number=2, ship_id=42, owner_id=8, x=200, y=200)
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="known-row",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldKnown(42),
                hull=FleetFieldKnown(13),
            ),
            build_option_sets=[
                FleetBuildOptionSet(hull_id=13, solution_rank_weight=1),
            ],
            events=[
                FleetEvidenceEvent(
                    event_id="evt-prior-sighting",
                    kind="sighting",
                    turn=1,
                    source="turnInfo.ships",
                    payload={"shipId": 42},
                )
            ],
            last_seen=FleetLastSeen(turn=1, x=100, y=100),
        )
    )
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="higher-weight-unlinked",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=50),
                hull=FleetFieldKnown(13),
                built_turn=FleetFieldKnown(1),
            ),
            build_option_sets=[
                FleetBuildOptionSet(hull_id=13, solution_rank_weight=999),
            ],
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    ledger = ledger_for_player(result, 8)
    known = next(rec for rec in ledger.records if rec.record_id == "known-row")
    assert known.fields.ship_id == FleetFieldKnown(42)
    assert not any(event.kind == "option_set_match" for event in known.events)
    assert known.events[-1].kind == "position_update"
    unlinked = next(rec for rec in ledger.records if rec.record_id == "higher-weight-unlinked")
    assert isinstance(unlinked.fields.ship_id, FleetFieldBounded)
    assert not record_has_direct_observation(unlinked)


def test_highest_solution_rank_weight_wins_among_id_bound_candidates():
    turn = single_ship_turn(turn_number=2, ship_id=7, owner_id=8, x=200, y=200)
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    snapshot.players[0].records.extend(
        [
            FleetShipRecord(
                record_id="low-weight",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=10),
                    hull=FleetFieldKnown(13),
                    built_turn=FleetFieldKnown(1),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(hull_id=13, solution_rank_weight=10),
                ],
            ),
            FleetShipRecord(
                record_id="high-weight",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=10),
                    hull=FleetFieldKnown(13),
                    built_turn=FleetFieldKnown(2),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(hull_id=13, solution_rank_weight=50),
                    FleetBuildOptionSet(hull_id=99, solution_rank_weight=100),
                ],
            ),
        ]
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    ledger = ledger_for_player(result, 8)
    winner = next(rec for rec in ledger.records if rec.record_id == "high-weight")
    assert winner.fields.ship_id == FleetFieldKnown(7)
    match_event = next(event for event in winner.events if event.kind == "option_set_match")
    assert match_event.payload["optionSetIndex"] == 0
    assert match_event.payload["solutionRankWeight"] == 50
    assert match_event.payload["tieBreak"] == "rank_weight"
    assert match_event.payload["candidateSetSize"] == 2
    loser = next(rec for rec in ledger.records if rec.record_id == "low-weight")
    assert isinstance(loser.fields.ship_id, FleetFieldBounded)


def test_equal_rank_weight_prefers_earliest_built_turn_then_ledger_order():
    turn = single_ship_turn(turn_number=3, ship_id=9, owner_id=8, x=200, y=200)
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    snapshot.players[0].records.extend(
        [
            FleetShipRecord(
                record_id="later-built",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=20),
                    hull=FleetFieldKnown(13),
                    built_turn=FleetFieldKnown(2),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(hull_id=13, solution_rank_weight=30),
                ],
            ),
            FleetShipRecord(
                record_id="earlier-built",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=20),
                    hull=FleetFieldKnown(13),
                    built_turn=FleetFieldKnown(1),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(hull_id=13, solution_rank_weight=30),
                ],
            ),
        ]
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    winner = next(
        rec for rec in ledger_for_player(result, 8).records if rec.record_id == "earlier-built"
    )
    match_event = next(event for event in winner.events if event.kind == "option_set_match")
    assert winner.fields.ship_id == FleetFieldKnown(9)
    assert match_event.payload["tieBreak"] == "built_turn"
    assert match_event.payload["candidateSetSize"] == 2


def test_equal_rank_weight_and_built_turn_uses_ledger_order():
    turn = single_ship_turn(turn_number=3, ship_id=9, owner_id=8, x=200, y=200)
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    snapshot.players[0].records.extend(
        [
            FleetShipRecord(
                record_id="first-in-ledger",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=20),
                    hull=FleetFieldKnown(13),
                    built_turn=FleetFieldKnown(1),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(hull_id=13, solution_rank_weight=30),
                ],
            ),
            FleetShipRecord(
                record_id="second-in-ledger",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=20),
                    hull=FleetFieldKnown(13),
                    built_turn=FleetFieldKnown(1),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(hull_id=13, solution_rank_weight=30),
                ],
            ),
        ]
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    winner = next(
        rec for rec in ledger_for_player(result, 8).records if rec.record_id == "first-in-ledger"
    )
    match_event = next(event for event in winner.events if event.kind == "option_set_match")
    assert winner.fields.ship_id == FleetFieldKnown(9)
    assert match_event.payload["tieBreak"] == "ledger_order"


def test_incompatible_option_sets_create_new_observed_row():
    turn = single_ship_turn(
        turn_number=6,
        ship_id=47,
        owner_id=8,
        x=2521,
        y=1943,
        hull_id=87,
    )
    ship = replace(
        turn.ships[0],
        beams=0,
        beamid=0,
        torps=0,
        torpedoid=0,
        bays=0,
        engineid=0,
    )
    turn = replace(turn, ships=[ship])
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    prior_events = [
        FleetEvidenceEvent(
            event_id="evt-acq",
            kind="scoreboard_delta",
            turn=5,
            source="scoreboard",
            payload={"warshipDelta": 1, "freighterDelta": 0},
        )
    ]
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="incompatible-placeholder",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=53),
                built_turn=FleetFieldKnown(5),
            ),
            build_option_sets=[
                FleetBuildOptionSet(
                    hull_id=91,
                    engine_id=1,
                    beam_id=2,
                    beam_count=4,
                    launcher_count=0,
                    solution_rank_weight=-350,
                ),
            ],
            events=list(prior_events),
            disposition="active",
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    ledger = ledger_for_player(result, 8)
    assert len(ledger.records) == 2
    placeholder = next(rec for rec in ledger.records if rec.record_id == "incompatible-placeholder")
    assert placeholder.fields.ship_id == FleetFieldBounded(operator="lte", value=53)
    assert placeholder.events == prior_events
    assert placeholder.disposition == "active"
    observed = next(rec for rec in ledger.records if rec.record_id != "incompatible-placeholder")
    assert observed.fields.ship_id == FleetFieldKnown(47)
    assert observed.fields.hull == FleetFieldKnown(87)
    assert observed.events[0].kind == "sighting"


def test_empty_option_sets_are_not_in_match_pool():
    turn = single_ship_turn(turn_number=2, ship_id=3, owner_id=8, x=200, y=200)
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="empty-sets-placeholder",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=5),
            ),
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    ledger = ledger_for_player(result, 8)
    assert len(ledger.records) == 2
    placeholder = next(rec for rec in ledger.records if rec.record_id == "empty-sets-placeholder")
    assert isinstance(placeholder.fields.ship_id, FleetFieldBounded)
    observed = next(rec for rec in ledger.records if rec.record_id != "empty-sets-placeholder")
    assert observed.fields.ship_id == FleetFieldKnown(3)


def test_id_bounds_applied_before_observation_match():
    """Scoreboard-inferred rows receive bounds before sighting arbitration."""
    current_turn = single_ship_turn(turn_number=2, ship_id=2, owner_id=8, x=200, y=200)
    score = replace(
        current_turn.scores[0],
        turn=2,
        ownerid=8,
        capitalships=2,
        freighters=0,
        shipchange=1,
        freighterchange=0,
    )
    current_turn = replace(current_turn, scores=[score])
    snapshot = ensure_fleet_baseline(628580, 1, current_turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="inferred-placeholder",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldUnknown(),
                hull=FleetFieldKnown(13),
                built_turn=FleetFieldKnown(1),
            ),
            build_option_sets=[
                FleetBuildOptionSet(hull_id=13, solution_rank_weight=20),
            ],
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

    record = next(
        rec
        for rec in ledger_for_player(result, 8).records
        if rec.record_id == "inferred-placeholder"
    )
    assert record.fields.ship_id == FleetFieldKnown(2)
    kinds = [event.kind for event in record.events]
    assert kinds.index("id_bound_tightened") < kinds.index("option_set_match")
    observation_kind = "position_update" if "position_update" in kinds else "sighting"
    assert kinds.index("option_set_match") < kinds.index(observation_kind)


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


def test_full_information_sighting_locks_all_components_including_zero_weapons():
    """Own-perspective ships: beams==0 is known-empty, not fog."""
    turn = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    ship = replace(
        turn.ships[0],
        beams=0,
        beamid=0,
        torps=0,
        torpedoid=0,
        bays=0,
        engineid=9,
    )
    turn = replace(turn, ships=[ship])

    result = ingest_turn_ship_observations(ensure_fleet_baseline(628580, 8, turn), turn)

    record = ledger_for_player(result, 8).records[0]
    assert record.fields.hull == FleetFieldKnown(value=13)
    assert record.fields.engine == FleetFieldKnown(value=9)
    assert record.fields.beams == FleetFieldKnown(value=0)
    assert record.fields.launchers == FleetFieldKnown(value=0)
    assert record.build_option_sets == [
        FleetBuildOptionSet(
            hull_id=13,
            engine_id=9,
            beam_id=None,
            torp_id=None,
            beam_count=0,
            launcher_count=0,
        )
    ]


def test_partial_sighting_does_not_lock_fog_zero_weapons():
    """Foreign ships: fog-of-war zeros stay unknown; only hull is reliable."""
    turn = single_ship_turn(turn_number=1, ship_id=42, owner_id=8, x=1000, y=2000)
    ship = replace(
        turn.ships[0],
        beams=0,
        beamid=0,
        torps=0,
        torpedoid=0,
        bays=0,
        engineid=0,
    )
    turn = replace(turn, ships=[ship])

    # Perspective 1 observing player 8's ship -- partial information.
    result = ingest_turn_ship_observations(ensure_fleet_baseline(628580, 1, turn), turn)

    record = ledger_for_player(result, 8).records[0]
    assert record.fields.ship_id == FleetFieldKnown(value=42)
    assert record.fields.hull == FleetFieldKnown(value=13)
    assert record.fields.engine == FleetFieldUnknown()
    assert record.fields.beams == FleetFieldUnknown()
    assert record.fields.launchers == FleetFieldUnknown()
    assert record.build_option_sets == [
        FleetBuildOptionSet(
            hull_id=13,
            engine_id=None,
            beam_id=None,
            torp_id=None,
            beam_count=None,
            launcher_count=None,
        )
    ]


def test_partial_sighting_merges_compatible_inferred_option_sets():
    """Fog hull lock keeps lock-compatible inferred fits and drops foreign hulls."""
    turn = single_ship_turn(
        turn_number=6,
        ship_id=47,
        owner_id=8,
        x=2521,
        y=1943,
        hull_id=87,
    )
    ship = replace(
        turn.ships[0],
        beams=0,
        beamid=0,
        torps=0,
        torpedoid=0,
        bays=0,
        engineid=0,
    )
    turn = replace(turn, ships=[ship])
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    ledger_for_player(snapshot, 8).records.append(
        FleetShipRecord(
            record_id="placeholder-warship",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=53),
                built_turn=FleetFieldKnown(5),
            ),
            build_option_sets=[
                FleetBuildOptionSet(
                    combo_id="combo_87_1_2_none_4_0",
                    label="Build Falcon: 1x StarDrive 1, 4x X-Ray Laser",
                    solution_rank_weight=-350,
                    hull_id=87,
                    engine_id=1,
                    beam_id=2,
                    beam_count=4,
                    launcher_count=0,
                ),
                FleetBuildOptionSet(
                    combo_id="combo_91_7_2_none_4_0",
                    label="Build Deep Space Scout: 1x Quantam Drive 7, 4x X-Ray Laser",
                    solution_rank_weight=-418,
                    hull_id=91,
                    engine_id=7,
                    beam_id=2,
                    beam_count=4,
                    launcher_count=0,
                ),
            ],
            display_default_option_set_index=0,
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    record = ledger_for_player(result, 8).records[0]
    assert record.record_id == "placeholder-warship"
    assert record.fields.ship_id == FleetFieldKnown(value=47)
    assert record.fields.hull == FleetFieldKnown(value=87)
    assert record.fields.engine == FleetFieldUnknown()
    assert record.fields.beams == FleetFieldUnknown()
    assert record.build_option_sets == [
        FleetBuildOptionSet(
            combo_id="combo_87_1_2_none_4_0",
            label="Build Falcon: 1x StarDrive 1, 4x X-Ray Laser",
            solution_rank_weight=-350,
            hull_id=87,
            engine_id=1,
            beam_id=2,
            beam_count=4,
            launcher_count=0,
        )
    ]
    assert record.display_default_option_set_index == 0
    assert any(event.kind == "option_set_match" for event in record.events)


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


def test_generic_freighter_hull_sentinel_matches_freighter_observation():
    turn = single_ship_turn(
        turn_number=2,
        ship_id=3,
        owner_id=8,
        x=200,
        y=200,
        hull_id=15,
        engine_id=9,
        beam_id=0,
        torpedoid=0,
    )
    ship = replace(turn.ships[0], beams=0, beamid=0, torps=0, torpedoid=0, bays=0)
    turn = replace(turn, ships=[ship])
    snapshot = ensure_fleet_baseline(628580, 8, turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="generic-freighter",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=5),
                built_turn=FleetFieldKnown(1),
            ),
            build_option_sets=[
                FleetBuildOptionSet(
                    combo_id="combo_freighter",
                    label="Freighter",
                    hull_id=0,
                    beam_count=0,
                    launcher_count=0,
                    solution_rank_weight=10,
                )
            ],
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    record = ledger_for_player(result, 8).records[0]
    assert record.record_id == "generic-freighter"
    assert record.fields.ship_id == FleetFieldKnown(3)
    match_event = next(event for event in record.events if event.kind == "option_set_match")
    assert match_event.payload["matchKind"] == "generic_freighter"


def test_generic_freighter_does_not_match_military_hull_for_non_fed():
    turn = single_ship_turn(
        turn_number=2,
        ship_id=3,
        owner_id=8,
        x=200,
        y=200,
        hull_id=24,
    )
    # Non-Fed race (Lizards = 2).
    players = [replace(player, raceid=2) if player.id == 8 else player for player in turn.players]
    turn = replace(turn, players=players, player=replace(turn.player, raceid=2))
    snapshot = ensure_fleet_baseline(628580, 8, turn)
    snapshot.players[0].records.append(
        FleetShipRecord(
            record_id="generic-freighter",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=5),
            ),
            build_option_sets=[
                FleetBuildOptionSet(
                    combo_id="combo_freighter",
                    hull_id=0,
                    beam_count=0,
                    launcher_count=0,
                    solution_rank_weight=10,
                )
            ],
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    ledger = ledger_for_player(result, 8)
    assert len(ledger.records) == 2
    placeholder = next(rec for rec in ledger.records if rec.record_id == "generic-freighter")
    assert isinstance(placeholder.fields.ship_id, FleetFieldBounded)


def test_fed_prefers_standard_match_over_generic_freighter_refit_fallback():
    turn = single_ship_turn(
        turn_number=2,
        ship_id=3,
        owner_id=1,
        x=200,
        y=200,
        hull_id=24,
    )
    players = [replace(player, raceid=1) if player.id == 1 else player for player in turn.players]
    turn = replace(turn, players=players, player=replace(turn.player, id=1, raceid=1))
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    ledger = ledger_for_player(snapshot, 1)
    ledger.records.extend(
        [
            FleetShipRecord(
                record_id="fed-refit-only",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=10),
                    built_turn=FleetFieldKnown(1),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(
                        combo_id="combo_freighter",
                        hull_id=0,
                        beam_count=0,
                        launcher_count=0,
                        solution_rank_weight=99,
                    )
                ],
            ),
            FleetShipRecord(
                record_id="standard-lcc",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=10),
                    built_turn=FleetFieldKnown(2),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(
                        hull_id=24,
                        engine_id=9,
                        beam_id=3,
                        torp_id=6,
                        beam_count=8,
                        launcher_count=6,
                        solution_rank_weight=10,
                    )
                ],
            ),
        ]
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    winner = next(
        rec for rec in ledger_for_player(result, 1).records if rec.record_id == "standard-lcc"
    )
    match_event = next(event for event in winner.events if event.kind == "option_set_match")
    assert match_event.payload["matchKind"] == "standard"
    assert winner.fields.ship_id == FleetFieldKnown(3)
    leftover = next(
        rec for rec in ledger_for_player(result, 1).records if rec.record_id == "fed-refit-only"
    )
    assert isinstance(leftover.fields.ship_id, FleetFieldBounded)


def test_fed_refit_fallback_matches_military_when_only_generic_freighter_candidate():
    turn = single_ship_turn(
        turn_number=2,
        ship_id=3,
        owner_id=1,
        x=200,
        y=200,
        hull_id=24,
    )
    players = [replace(player, raceid=1) if player.id == 1 else player for player in turn.players]
    turn = replace(turn, players=players, player=replace(turn.player, id=1, raceid=1))
    snapshot = ensure_fleet_baseline(628580, 1, turn)
    ledger_for_player(snapshot, 1).records.append(
        FleetShipRecord(
            record_id="fed-refit",
            fields=FleetShipRecordFields(
                ship_id=FleetFieldBounded(operator="lte", value=10),
            ),
            build_option_sets=[
                FleetBuildOptionSet(
                    combo_id="combo_freighter",
                    hull_id=0,
                    beam_count=0,
                    launcher_count=0,
                    solution_rank_weight=10,
                )
            ],
        )
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    record = next(
        rec for rec in ledger_for_player(result, 1).records if rec.record_id == "fed-refit"
    )
    match_event = next(event for event in record.events if event.kind == "option_set_match")
    assert match_event.payload["matchKind"] == "fed_refit"
    assert record.fields.ship_id == FleetFieldKnown(3)


def test_homeworld_mdsf_transwarp_preferred_over_generic_freighter():
    """Starter MDSF+Transwarp option set is standard match; beats generic freighter."""
    turn = single_ship_turn(
        turn_number=3,
        ship_id=2,
        owner_id=8,
        x=200,
        y=200,
        hull_id=16,
        engine_id=9,
        beam_id=0,
        torpedoid=0,
    )
    ship = replace(turn.ships[0], beams=0, beamid=0, torps=0, torpedoid=0, bays=0)
    turn = replace(turn, ships=[ship])
    snapshot = ensure_fleet_baseline(628580, 8, turn)
    snapshot.players[0].records.extend(
        [
            FleetShipRecord(
                record_id="homeworld-mdsf",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=11),
                    hull=FleetFieldKnown(16),
                    engine=FleetFieldKnown(9),
                    built_turn=FleetFieldKnown(1),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(
                        hull_id=16,
                        engine_id=9,
                        beam_count=0,
                        launcher_count=0,
                        solution_rank_weight=0,
                    )
                ],
                events=[
                    FleetEvidenceEvent(
                        event_id="evt-hw",
                        kind="scoreboard_delta",
                        turn=3,
                        source="scoreboard",
                        payload={
                            "shipClass": "freighter",
                            "homeworldStartingInventory": True,
                        },
                    )
                ],
            ),
            FleetShipRecord(
                record_id="generic-freighter",
                fields=FleetShipRecordFields(
                    ship_id=FleetFieldBounded(operator="lte", value=22),
                    built_turn=FleetFieldKnown(1),
                ),
                build_option_sets=[
                    FleetBuildOptionSet(
                        combo_id="combo_freighter",
                        hull_id=0,
                        beam_count=0,
                        launcher_count=0,
                        solution_rank_weight=50,
                    )
                ],
            ),
        ]
    )

    result = ingest_turn_ship_observations(snapshot, turn)

    winner = next(
        rec for rec in ledger_for_player(result, 8).records if rec.record_id == "homeworld-mdsf"
    )
    match_event = next(event for event in winner.events if event.kind == "option_set_match")
    assert match_event.payload["matchKind"] == "standard"
    assert winner.fields.ship_id == FleetFieldKnown(2)
    leftover = next(
        rec for rec in ledger_for_player(result, 8).records if rec.record_id == "generic-freighter"
    )
    assert isinstance(leftover.fields.ship_id, FleetFieldBounded)
