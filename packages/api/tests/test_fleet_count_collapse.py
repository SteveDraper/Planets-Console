"""Tests for fleet count collapse (#259)."""

from __future__ import annotations

import uuid
from dataclasses import replace

from api.analytics.fleet.chain import ensure_fleet_baseline
from api.analytics.fleet.count_collapse import apply_fleet_count_collapse
from api.analytics.fleet.observation_ingest import (
    apply_id_bounds_then_observations,
    ingest_turn_ship_observations,
    record_has_direct_observation,
)
from api.analytics.fleet.turn_context import FleetTurnContext
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetBuildOptionSet,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.concepts.hulls import hull_is_freighter
from api.models.game import TurnInfo
from api.models.player import Score

from tests.fleet_fixtures import ledger_for_player, single_ship_turn

PLAYER_ID = 8
WARSHIP_HULL_ID = 1
FREIGHTER_HULL_ID = 15


def _scoreboard_delta_event(*, turn: int, ship_class: str) -> FleetEvidenceEvent:
    return FleetEvidenceEvent(
        event_id=str(uuid.uuid4()),
        kind="scoreboard_delta",
        turn=turn,
        source="scoreboard",
        payload={
            "shipClass": ship_class,
            "warshipDelta": 1 if ship_class == "warship" else 0,
            "freighterDelta": 1 if ship_class == "freighter" else 0,
        },
    )


def _turn_with_player_score(
    turn: TurnInfo,
    *,
    owner_id: int,
    turn_number: int,
    capitalships: int,
    freighters: int,
) -> TurnInfo:
    scores: list[Score] = []
    replaced = False
    for score in turn.scores:
        if score.ownerid == owner_id and score.turn == turn_number:
            scores.append(
                replace(
                    score,
                    capitalships=capitalships,
                    freighters=freighters,
                )
            )
            replaced = True
        else:
            scores.append(score)
    if not replaced:
        template = next(iter(turn.scores))
        scores.append(
            replace(
                template,
                ownerid=owner_id,
                turn=turn_number,
                capitalships=capitalships,
                freighters=freighters,
            )
        )
    return replace(turn, scores=scores)


def _absorbable_row(
    record_id: str,
    *,
    turn: int,
    ship_class: str,
    ship_id: FleetFieldBounded | FleetFieldUnknown = FleetFieldBounded(operator="lte", value=109),
    built_turn: FleetFieldKnown | FleetFieldUnknown = FleetFieldUnknown(),
    build_option_sets: list[FleetBuildOptionSet] | None = None,
) -> FleetShipRecord:
    return FleetShipRecord(
        record_id=record_id,
        disposition="active",
        fields=FleetShipRecordFields(
            ship_id=ship_id,
            built_turn=built_turn,
        ),
        build_option_sets=list(build_option_sets or []),
        events=[_scoreboard_delta_event(turn=turn, ship_class=ship_class)],
    )


def _survivor_row(
    record_id: str,
    ship_id: int,
    *,
    hull_id: int = WARSHIP_HULL_ID,
    built_turn: FleetFieldKnown | FleetFieldUnknown = FleetFieldUnknown(),
    build_option_sets: list[FleetBuildOptionSet] | None = None,
) -> FleetShipRecord:
    return FleetShipRecord(
        record_id=record_id,
        disposition="active",
        fields=FleetShipRecordFields(
            ship_id=FleetFieldKnown(ship_id),
            hull=FleetFieldKnown(hull_id),
            built_turn=built_turn,
        ),
        build_option_sets=list(build_option_sets or []),
    )


def _ledger_with_records(
    turn: TurnInfo,
    records: list[FleetShipRecord],
    *,
    player_id: int = PLAYER_ID,
) -> FleetAcquisitionLedger:
    return FleetAcquisitionLedger(
        player_id=player_id,
        player_name="test",
        records=list(records),
    )


def _assert_warship_hull(turn: TurnInfo, hull_id: int) -> None:
    hull = next(h for h in turn.hulls if h.id == hull_id)
    assert not hull_is_freighter(hull)


def test_happy_path_collapses_four_absorbables_onto_four_survivors():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=4,
        freighters=0,
    )
    _assert_warship_hull(turn, WARSHIP_HULL_ID)

    absorbables = [
        _absorbable_row(f"abs-{index}", turn=turn_number, ship_class="warship")
        for index in range(4)
    ]
    survivors = [_survivor_row(f"sur-{ship_id}", ship_id) for ship_id in (100, 101, 102, 103)]
    ledger = _ledger_with_records(turn, absorbables + survivors)

    apply_fleet_count_collapse(ledger, turn)

    active = [record for record in ledger.records if record.disposition == "active"]
    merged = [record for record in ledger.records if record.disposition == "merged"]
    assert len(active) == 4
    assert len(merged) == 4
    for record in merged:
        assert isinstance(record.fields.ship_id, FleetFieldKnown)
        survivor_ids = {100, 101, 102, 103}
        assert record.fields.ship_id.value in survivor_ids
        collapse_events = [event for event in record.events if event.kind == "count_collapse"]
        assert len(collapse_events) == 1
        assert collapse_events[0].payload["shipClass"] == "warship"
        assert not record_has_direct_observation(record)
    for survivor in survivors:
        collapse_events = [event for event in survivor.events if event.kind == "count_collapse"]
        assert len(collapse_events) == 1
    assert ledger.discrepancy is None


def test_soft_inheritance_copies_built_turn_and_option_sets():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=0,
    )
    option_sets = [
        FleetBuildOptionSet(hull_id=WARSHIP_HULL_ID, engine_id=9, solution_rank_weight=5),
    ]
    absorbable = _absorbable_row(
        "absorb",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=50),
        built_turn=FleetFieldKnown(3),
        build_option_sets=option_sets,
    )
    absorbable.display_default_option_set_index = 0
    survivor = _survivor_row("survivor", 40)
    ledger = _ledger_with_records(turn, [absorbable, survivor])

    apply_fleet_count_collapse(ledger, turn)

    assert absorbable.disposition == "merged"
    assert survivor.disposition == "active"
    assert survivor.fields.built_turn == FleetFieldKnown(3)
    assert survivor.build_option_sets == option_sets
    assert survivor.display_default_option_set_index == 0
    assert survivor.fields.ship_id == FleetFieldKnown(40)
    assert survivor.fields.hull == FleetFieldKnown(WARSHIP_HULL_ID)


def test_most_constrained_absorbable_collapses_first():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=0,
    )
    tight = _absorbable_row(
        "tight",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=50),
    )
    loose = _absorbable_row(
        "loose",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=109),
    )
    survivor = _survivor_row("survivor", 40)
    ledger = _ledger_with_records(turn, [tight, loose, survivor])

    apply_fleet_count_collapse(ledger, turn)

    assert tight.disposition == "merged"
    assert tight.fields.ship_id == FleetFieldKnown(40)
    assert loose.disposition == "active"
    assert isinstance(loose.fields.ship_id, FleetFieldBounded)


def test_fully_unknown_absorbable_collapses_onto_survivor():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=0,
    )
    absorbable = _absorbable_row(
        "unknown",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldUnknown(),
    )
    survivor = _survivor_row("survivor", 77)
    ledger = _ledger_with_records(turn, [absorbable, survivor])

    apply_fleet_count_collapse(ledger, turn)

    assert absorbable.disposition == "merged"
    assert absorbable.fields.ship_id == FleetFieldKnown(77)
    collapse = next(event for event in absorbable.events if event.kind == "count_collapse")
    assert collapse.payload["constraintTightness"] == "unknown"
    assert collapse.payload["shipId"] == 77


def test_bounded_preferred_over_fully_unknown_absorbable():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=0,
    )
    unknown = _absorbable_row(
        "unknown",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldUnknown(),
    )
    bounded = _absorbable_row(
        "bounded",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=50),
    )
    survivor = _survivor_row("survivor", 40)
    ledger = _ledger_with_records(turn, [unknown, bounded, survivor])

    apply_fleet_count_collapse(ledger, turn)

    assert bounded.disposition == "merged"
    assert bounded.fields.ship_id == FleetFieldKnown(40)
    assert unknown.disposition == "active"
    assert isinstance(unknown.fields.ship_id, FleetFieldUnknown)


def test_survivor_pick_uses_lowest_compatible_ship_id():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=0,
    )
    absorbable = _absorbable_row(
        "absorb",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=50),
    )
    survivors = [_survivor_row("sur-30", 30), _survivor_row("sur-20", 20)]
    ledger = _ledger_with_records(turn, [absorbable, *survivors])

    apply_fleet_count_collapse(ledger, turn)

    assert absorbable.disposition == "merged"
    assert absorbable.fields.ship_id == FleetFieldKnown(20)
    collapse = next(event for event in absorbable.events if event.kind == "count_collapse")
    assert collapse.payload["tieBreak"] == "ship_id"
    assert collapse.payload["candidateSetSize"] == 2


def test_cross_class_absorbable_does_not_merge_onto_other_class_survivor():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=1,
    )
    warship_absorbable = _absorbable_row(
        "warship-abs",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=100),
    )
    freighter_absorbable = _absorbable_row(
        "freighter-abs",
        turn=turn_number,
        ship_class="freighter",
        ship_id=FleetFieldBounded(operator="lte", value=100),
    )
    warship_survivor = _survivor_row("warship-sur", 50, hull_id=WARSHIP_HULL_ID)
    freighter_survivor = _survivor_row("freighter-sur", 60, hull_id=FREIGHTER_HULL_ID)
    ledger = _ledger_with_records(
        turn,
        [warship_absorbable, freighter_absorbable, warship_survivor, freighter_survivor],
    )

    apply_fleet_count_collapse(ledger, turn)

    assert warship_absorbable.disposition == "merged"
    assert warship_absorbable.fields.ship_id == FleetFieldKnown(50)
    assert freighter_absorbable.disposition == "merged"
    assert freighter_absorbable.fields.ship_id == FleetFieldKnown(60)
    assert warship_survivor.disposition == "active"
    assert freighter_survivor.disposition == "active"


def test_id_gate_blocks_incompatible_survivor():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=0,
    )
    absorbable = _absorbable_row(
        "absorb",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=50),
    )
    survivor = _survivor_row("survivor", 90)
    ledger = _ledger_with_records(turn, [absorbable, survivor])

    apply_fleet_count_collapse(ledger, turn)

    assert absorbable.disposition == "active"
    assert survivor.disposition == "active"


def test_missing_score_is_no_op():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = replace(
        turn,
        scores=[score for score in turn.scores if score.ownerid != PLAYER_ID],
    )
    absorbables = [
        _absorbable_row(f"abs-{index}", turn=turn_number, ship_class="warship")
        for index in range(2)
    ]
    survivors = [_survivor_row("sur-1", 100), _survivor_row("sur-2", 101)]
    ledger = _ledger_with_records(turn, absorbables + survivors)

    apply_fleet_count_collapse(ledger, turn)

    assert all(record.disposition == "active" for record in ledger.records)


def test_residual_over_count_without_absorbables_leaves_rows_active():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=2,
        freighters=0,
    )
    survivors = [
        _survivor_row("sur-1", 100),
        _survivor_row("sur-2", 101),
        _survivor_row("sur-3", 102),
    ]
    ledger = _ledger_with_records(turn, survivors)

    apply_fleet_count_collapse(ledger, turn)

    assert len([record for record in ledger.records if record.disposition == "active"]) == 3
    assert ledger.discrepancy is None


def test_observation_match_preferred_over_count_collapse():
    turn = single_ship_turn(turn_number=2, ship_id=7, owner_id=PLAYER_ID, x=200, y=200)
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=2,
        capitalships=10,
        freighters=0,
    )
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

    ledger = ledger_for_player(result, PLAYER_ID)
    winner = next(rec for rec in ledger.records if rec.record_id == "high-weight")
    assert winner.fields.ship_id == FleetFieldKnown(7)
    assert any(event.kind == "option_set_match" for event in winner.events)
    collapse_events = (
        event
        for record in ledger.records
        for event in record.events
        if event.kind == "count_collapse"
    )
    assert not any(collapse_events)


def test_apply_id_bounds_then_observations_runs_collapse_after_match():
    turn_number = 2
    turn = single_ship_turn(turn_number=turn_number, ship_id=99, owner_id=PLAYER_ID, x=0, y=0)
    turn = replace(turn, ships=[])
    turn = _turn_with_player_score(
        turn,
        owner_id=PLAYER_ID,
        turn_number=turn_number,
        capitalships=1,
        freighters=0,
    )
    absorbable = _absorbable_row(
        "absorb",
        turn=turn_number,
        ship_class="warship",
        ship_id=FleetFieldBounded(operator="lte", value=50),
    )
    survivor = _survivor_row("survivor", 1)
    ledger = _ledger_with_records(turn, [absorbable, survivor])
    context = FleetTurnContext.from_turn(turn)

    apply_id_bounds_then_observations(ledger, context, perspective=PLAYER_ID)

    assert absorbable.disposition == "merged"
    assert absorbable.fields.ship_id == FleetFieldKnown(1)
    assert survivor.disposition == "active"
