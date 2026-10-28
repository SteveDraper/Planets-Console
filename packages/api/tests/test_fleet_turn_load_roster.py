"""Turn-load fleet roster: stored ledgers and sightings before the chain."""

from __future__ import annotations

from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.fleet_table_player_run import (
    FleetLedgerWireProgressTracker,
    FleetPlayerStreamSession,
    ScheduledFleetPlayer,
)
from api.analytics.fleet.fleet_table_stream_rows import (
    CachedCompletePlayerAdmission,
    RosterThenScheduleAdmission,
    iter_fleet_table_stream_events,
    resolve_player_stream_admission,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    _node_complete_stream_events,
    _query_context_for_services,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)


def _living_ships(turn, player_id: int):
    return [ship for ship in turn.ships if ship.turnkilled == 0 and ship.ownerid == player_id]


def _services(turn):
    return build_ephemeral_fleet_compute_services(
        turn,
        game_id=turn.game.id,
        perspective=turn.player.id,
    )


def _stored_ship_ledger(turn, player_id: int) -> PersistedFleetLedger:
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(
            player_id=player_id,
            player_name="Stored",
            records=[
                FleetShipRecord(
                    record_id="stored-ship",
                    fields=FleetShipRecordFields(ship_id=FleetFieldKnown(4242)),
                )
            ],
        ),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )


def _paint_ledger(admission) -> dict[str, object]:
    assert isinstance(admission, RosterThenScheduleAdmission)
    event = admission.events[0]
    assert event["type"] == "roster_paint"
    ledger = event["ledger"]
    assert isinstance(ledger, dict)
    return ledger


def test_generation_behind_ledger_is_painted_before_scheduling(sample_turn):
    services = _services(sample_turn)
    player_id = sample_turn.scores[0].ownerid
    turn_number = sample_turn.settings.turn
    services.persistence.put_ledger(
        sample_turn.game.id,
        sample_turn.player.id,
        turn_number,
        player_id,
        _stored_ship_ledger(sample_turn, player_id),
    )
    services.persistence._bump_durable_evidence_mark(
        sample_turn.game.id,
        sample_turn.player.id,
        player_id,
        turn_number,
    )
    stored = services.persistence.get_ledger(
        sample_turn.game.id,
        sample_turn.player.id,
        turn_number,
        player_id,
    )
    assert stored is not None
    assert not services.persistence.ledger_is_ensure_final(
        sample_turn.game.id,
        sample_turn.player.id,
        turn_number,
        player_id,
        stored,
    )

    admission = resolve_player_stream_admission(
        services.persistence,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=turn_number,
        player_id=player_id,
        turn=sample_turn,
    )

    ledger = _paint_ledger(admission)
    assert admission.events[0]["paint"] == "ledger"
    records = ledger["records"]
    assert isinstance(records, list)
    assert records[0]["recordId"] == "stored-ship"
    assert records[0]["fields"]["shipId"] == {"kind": "known", "value": 4242}
    assert "possiblyLost" not in records[0]["qualifiers"]
    assert "alibi" not in records[0]["qualifiers"]


def test_missing_ledger_lists_this_turn_sightings_in_turn_file_order(sample_turn):
    services = _services(sample_turn)
    player_id = next(
        player_id
        for player_id in {ship.ownerid for ship in sample_turn.ships}
        if _living_ships(sample_turn, player_id)
    )
    ships = _living_ships(sample_turn, player_id)
    full_information = player_id == sample_turn.player.id

    admission = resolve_player_stream_admission(
        services.persistence,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
        player_id=player_id,
        turn=sample_turn,
    )

    ledger = _paint_ledger(admission)
    assert admission.events[0]["paint"] == "sightings"
    records = ledger["records"]
    assert isinstance(records, list)
    painted_ids = [record["fields"]["shipId"]["value"] for record in records]
    assert painted_ids == [ship.id for ship in ships]
    for ship, record in zip(ships, records, strict=True):
        qualifiers = record["qualifiers"]
        assert "possiblyLost" not in qualifiers
        assert "alibi" not in qualifiers
        hull = record["fields"]["hull"]
        if ship.hullid > 0:
            assert hull == {"kind": "known", "value": ship.hullid}
        else:
            assert hull["kind"] == "unknown"
        if not full_information and ship.engineid <= 0:
            assert record["fields"]["engine"]["kind"] == "unknown"


def test_zero_sightings_paint_an_empty_roster(sample_turn):
    services = _services(sample_turn)
    owners = {ship.ownerid for ship in sample_turn.ships if ship.turnkilled == 0}
    player_id = next(player.id for player in sample_turn.players if player.id not in owners)

    admission = resolve_player_stream_admission(
        services.persistence,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
        player_id=player_id,
        turn=sample_turn,
    )

    ledger = _paint_ledger(admission)
    assert admission.events[0]["paint"] == "sightings"
    assert ledger["records"] == []


def test_stored_empty_final_ledger_stays_cached_complete(sample_turn):
    services = _services(sample_turn)
    player_id = sample_turn.scores[0].ownerid
    services.persistence.put_ledger(
        sample_turn.game.id,
        sample_turn.player.id,
        sample_turn.settings.turn,
        player_id,
        PersistedFleetLedger(
            ledger=FleetAcquisitionLedger(player_id=player_id, player_name="Empty"),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )

    admission = resolve_player_stream_admission(
        services.persistence,
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn_number=sample_turn.settings.turn,
        player_id=player_id,
        turn=sample_turn,
    )

    assert isinstance(admission, CachedCompletePlayerAdmission)
    ledger_event = next(event for event in admission.events if event["type"] == "ledger_updated")
    complete = next(event for event in admission.events if event["type"] == "complete")
    assert ledger_event["ledger"]["records"] == []
    assert complete["isFinal"] is True


def test_stream_yields_stored_ledger_without_running_the_chain(sample_turn, monkeypatch):
    services = _services(sample_turn)
    player_id = sample_turn.scores[0].ownerid
    turn_number = sample_turn.settings.turn
    services.persistence.put_ledger(
        sample_turn.game.id,
        sample_turn.player.id,
        turn_number,
        player_id,
        _stored_ship_ledger(sample_turn, player_id),
    )
    services.persistence._bump_durable_evidence_mark(
        sample_turn.game.id,
        sample_turn.player.id,
        player_id,
        turn_number,
    )
    scheduled: list[int] = []

    def _schedule(_scheduler, **kwargs):
        scheduled.append(kwargs["player_id"])
        session = FleetPlayerStreamSession(
            player_id=kwargs["player_id"],
            turn=kwargs["turn"],
            game_id=kwargs["game_id"],
            perspective=kwargs["perspective"],
        )
        return ScheduledFleetPlayer(player_id=kwargs["player_id"], session=session)

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_controller.schedule_fleet_player_run",
        _schedule,
    )
    reset_fleet_table_stream_scheduler_for_tests()
    stream = iter_fleet_table_stream_events(
        sample_turn,
        (player_id,),
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        fleet_services=services,
        persistence=services.persistence,
        scheduler=FleetTableStreamScheduler(),
        query_context=_query_context_for_services(services, host_turn=sample_turn),
    )
    try:
        first = next(stream)
    finally:
        stream.close()

    assert scheduled == [player_id]
    assert first["type"] == "roster_paint"
    assert first["paint"] == "ledger"
    assert first["ledger"]["records"][0]["recordId"] == "stored-ship"


def test_earlier_turn_progress_does_not_replace_the_turn_load_roster(sample_turn):
    player_id = sample_turn.scores[0].ownerid
    persisted = PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=player_id, player_name="Prior"),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    tracker = FleetLedgerWireProgressTracker(host_turn=sample_turn)
    events = _node_complete_stream_events(
        scope_turn=sample_turn.settings.turn - 1,
        host_turn_number=sample_turn.settings.turn,
        tracker=tracker,
        persisted=persisted,
        session_turn=sample_turn,
        cancelled=False,
    )
    updated = [event for event in events if event.get("type") == "ledger_updated"]
    assert updated
    assert updated[0]["replacesTurnLoad"] is False

    host_events = _node_complete_stream_events(
        scope_turn=sample_turn.settings.turn,
        host_turn_number=sample_turn.settings.turn,
        tracker=FleetLedgerWireProgressTracker(host_turn=sample_turn),
        persisted=persisted,
        session_turn=sample_turn,
        cancelled=False,
    )
    host_updated = [event for event in host_events if event.get("type") == "ledger_updated"]
    assert host_updated
    assert "replacesTurnLoad" not in host_updated[0]
