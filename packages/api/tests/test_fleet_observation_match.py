"""Tests for fleet observation option-set match arbitration."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import ensure_fleet_baseline
from api.analytics.fleet.field_constraints import record_has_direct_observation
from api.analytics.fleet.observation_ingest import (
    ingest_turn_ship_observations,
)
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldKnown,
    FleetLastSeen,
    FleetShipRecord,
    FleetShipRecordFields,
)

from tests.fleet_fixtures import ledger_for_player, single_ship_turn


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
