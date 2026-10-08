"""Non-accelerated turn 2 seeds the starting freighter the baseline subtracts.

A built-turn-1 sighting of that hull fills the slot on the opening reveal.
On the accelerated first-reliable row the same record leaves the seed in place.
"""

from dataclasses import replace

from api.analytics.fleet.chain import (
    advance_snapshot_to_turn,
    apply_fleet_turn_delta,
    ensure_fleet_baseline,
)
from api.analytics.fleet.inferred_acquisition_ingest import ingest_turn_inferred_acquisitions
from api.analytics.fleet.types import FleetFieldKnown, FleetShipRecord, FleetShipRecordFields
from api.concepts.races import HORWASP_RACE_ID

from tests.fixtures.military_score_inference import with_score_owners_in_roster
from tests.fleet_fixtures import ledger_for_player

_STARTER_HULL_ID = 16
_STARTER_ENGINE_ID = 9
_OWNER_ID = 35


def _score(template, **fields):
    return replace(
        template,
        prioritypoints=0,
        prioritypointchange=0,
        inventoryscore=0,
        inventorychange=0,
        percent=0.0,
        percentchange=0.0,
        victoryscore=0,
        victoryscorechange=0,
        **fields,
    )


def _opening_turn(
    sample_turn,
    *,
    turn_number: int,
    freighters: int,
    capitalships: int,
    homeworld_has_starbase: bool = True,
    race_id: int | None = None,
    ships: tuple | None = None,
):
    template = sample_turn.scores[0]
    score = _score(
        template,
        ownerid=_OWNER_ID,
        turn=turn_number,
        militaryscore=2110 if homeworld_has_starbase else 0,
        militarychange=2110 if homeworld_has_starbase else 0,
        capitalships=capitalships,
        shipchange=capitalships,
        freighters=freighters,
        freighterchange=freighters,
        starbases=1 if homeworld_has_starbase else 0,
        starbasechange=1 if homeworld_has_starbase else 0,
        planets=1,
        planetchange=1,
    )
    turn = with_score_owners_in_roster(
        replace(
            sample_turn,
            settings=replace(
                sample_turn.settings,
                turn=turn_number,
                acceleratedturns=0,
                homeworldhasstarbase=homeworld_has_starbase,
            ),
            scores=(score,),
            ships=sample_turn.ships if ships is None else ships,
        )
    )
    if race_id is not None:
        turn = replace(
            turn,
            players=tuple(
                replace(player, raceid=race_id) if player.id == _OWNER_ID else player
                for player in turn.players
            ),
        )
    return turn


def _starter_ship(sample_turn):
    return replace(
        sample_turn.ships[0],
        id=1,
        ownerid=_OWNER_ID,
        hullid=_STARTER_HULL_ID,
        engineid=_STARTER_ENGINE_ID,
        turn=1,
        beams=0,
        bays=0,
        torps=0,
        beamid=0,
        torpedoid=0,
    )


def _active(ledger):
    return [record for record in ledger.records if record.disposition == "active"]


def _is_starting_freighter(record) -> bool:
    return any(
        event.kind == "scoreboard_delta" and event.payload.get("homeworldStartingInventory") is True
        for event in record.events
    )


def _is_turn_freighter_placeholder(record, *, shell_turn: int) -> bool:
    return any(
        event.kind == "scoreboard_delta"
        and event.turn == shell_turn
        and event.payload.get("shipClass") == "freighter"
        and event.payload.get("homeworldStartingInventory") is not True
        for event in record.events
    )


def _is_turn_warship_placeholder(record, *, shell_turn: int) -> bool:
    return any(
        event.kind == "scoreboard_delta"
        and event.turn == shell_turn
        and event.payload.get("shipClass") == "warship"
        for event in record.events
    )


def _ingest(sample_turn, turn):
    return ingest_turn_inferred_acquisitions(
        ensure_fleet_baseline(sample_turn.game.id, 1, turn),
        turn,
    )


def test_opening_reveal_unseen_owner_gets_the_starting_freighter(sample_turn):
    turn = _opening_turn(sample_turn, turn_number=2, freighters=1, capitalships=1)
    ledger = ledger_for_player(_ingest(sample_turn, turn), _OWNER_ID)

    starters = [record for record in _active(ledger) if _is_starting_freighter(record)]
    assert len(starters) == 1
    assert starters[0].fields.hull == FleetFieldKnown(_STARTER_HULL_ID)
    assert starters[0].fields.engine == FleetFieldKnown(_STARTER_ENGINE_ID)
    assert starters[0].fields.built_turn == FleetFieldKnown(1)
    turn2_freighters = [
        record for record in ledger.records if _is_turn_freighter_placeholder(record, shell_turn=2)
    ]
    assert turn2_freighters == []
    warships = [
        record for record in _active(ledger) if _is_turn_warship_placeholder(record, shell_turn=2)
    ]
    assert len(warships) == 1


def test_opening_reveal_extra_freighter_is_a_turn2_placeholder(sample_turn):
    turn = _opening_turn(sample_turn, turn_number=2, freighters=2, capitalships=0)
    ledger = ledger_for_player(_ingest(sample_turn, turn), _OWNER_ID)

    starters = [record for record in _active(ledger) if _is_starting_freighter(record)]
    placeholders = [
        record for record in _active(ledger) if _is_turn_freighter_placeholder(record, shell_turn=2)
    ]
    assert len(starters) == 1
    assert len(placeholders) == 1


def test_opening_reveal_turn1_sighting_fills_the_starting_freighter(sample_turn):
    ship = _starter_ship(sample_turn)
    turn1 = _opening_turn(
        sample_turn,
        turn_number=1,
        freighters=0,
        capitalships=0,
        ships=(ship,),
    )
    carried = apply_fleet_turn_delta(
        ensure_fleet_baseline(sample_turn.game.id, 1, turn1),
        turn1,
    )
    turn2 = _opening_turn(
        sample_turn,
        turn_number=2,
        freighters=1,
        capitalships=1,
        ships=(),
    )
    snapshot = ingest_turn_inferred_acquisitions(
        advance_snapshot_to_turn(
            carried,
            turn2,
            game_id=sample_turn.game.id,
            perspective=1,
        ),
        turn2,
    )
    ledger = ledger_for_player(snapshot, _OWNER_ID)

    assert not any(_is_starting_freighter(record) for record in ledger.records)
    sighted = [
        record
        for record in _active(ledger)
        if record.fields.hull == FleetFieldKnown(_STARTER_HULL_ID)
        and record.fields.ship_id == FleetFieldKnown(ship.id)
    ]
    assert len(sighted) == 1
    assert sighted[0].fields.built_turn == FleetFieldKnown(1)


def test_accelerated_first_reliable_built_turn_one_freighter_still_seeds(sample_turn):
    opening = _opening_turn(sample_turn, turn_number=3, freighters=1, capitalships=0)
    turn = replace(opening, settings=replace(opening.settings, acceleratedturns=3))
    snapshot = ensure_fleet_baseline(sample_turn.game.id, 1, turn)
    ledger = ledger_for_player(snapshot, _OWNER_ID)
    ledger.records.append(
        FleetShipRecord(
            record_id="window-mdsf",
            fields=FleetShipRecordFields(
                built_turn=FleetFieldKnown(1),
                hull=FleetFieldKnown(_STARTER_HULL_ID),
            ),
        )
    )

    ingest_turn_inferred_acquisitions(snapshot, turn)

    starters = [record for record in ledger.records if _is_starting_freighter(record)]
    assert len(starters) == 1
    assert starters[0].record_id != "window-mdsf"


def test_opening_reveal_horwasp_without_starbase_still_gets_the_starting_freighter(sample_turn):
    turn = _opening_turn(
        sample_turn,
        turn_number=2,
        freighters=1,
        capitalships=0,
        homeworld_has_starbase=False,
        race_id=HORWASP_RACE_ID,
    )
    ledger = ledger_for_player(_ingest(sample_turn, turn), _OWNER_ID)

    starters = [record for record in _active(ledger) if _is_starting_freighter(record)]
    placeholders = [
        record for record in ledger.records if _is_turn_freighter_placeholder(record, shell_turn=2)
    ]
    assert len(starters) == 1
    assert placeholders == []
