"""Tests for the multiplexed fleet table NDJSON stream."""

from __future__ import annotations

import json

import pytest
from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.fleet_table_stream_rows import (
    ScheduledFleetPlayer,
    drain_available_multiplex_events,
    iter_fleet_table_stream_events,
    schedule_fleet_player_run,
    tag_fleet_table_stream_event,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_to_json,
)
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.transport.fleet_table_stream import (
    TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
    fleet_complete_event,
    stream_fleet_table_ndjson,
)


def _events_for_players(
    sample_turn,
    player_ids: tuple[int, ...],
    *,
    scheduler: FleetTableStreamScheduler | None = None,
    services=None,
) -> list[dict[str, object]]:
    resolved_services = services or build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    stream = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=resolved_services,
        persistence=resolved_services.persistence,
        scheduler=scheduler,
    )
    events: list[dict[str, object]] = []
    expected_players = set(player_ids)
    finished_players: set[int] = set()
    try:
        for event in stream:
            events.append(event)
            if event.get("type") in ("complete", "error") and isinstance(
                event.get("playerId"), int
            ):
                finished_players.add(event["playerId"])
            if finished_players == expected_players:
                break
    finally:
        stream.close()
    return events


def test_fleet_table_stream_early_close_releases_scope_for_reconnect(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    player_id = sample_turn.scores[0].ownerid
    services.persistence.put_ledger(
        628580,
        1,
        sample_turn.settings.turn,
        player_id,
        PersistedFleetLedger(
            ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )
    player_ids = (player_id,)

    first = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=services.persistence,
        scheduler=scheduler,
    )
    first.close()

    second = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=services.persistence,
        scheduler=scheduler,
    )
    try:
        first_event = next(second)
        assert first_event.get("detail") != TABLE_STREAM_ALREADY_ACTIVE_DETAIL
    finally:
        second.close()


def test_fleet_table_stream_reconnect_returns_conflict_while_active(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    scope = FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    try:
        services = build_ephemeral_fleet_compute_services(
            sample_turn,
            game_id=628580,
            perspective=1,
        )
        replacement = iter_fleet_table_stream_events(
            sample_turn,
            (sample_turn.scores[0].ownerid,),
            game_id=628580,
            perspective=1,
            fleet_services=services,
            persistence=services.persistence,
            scheduler=scheduler,
        )
        assert next(replacement) == {
            "type": "error",
            "detail": TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
        }
        replacement.close()
    finally:
        scheduler.end_fleet_table_stream(scope, (), stream_token=stream_token)


def test_fleet_table_stream_reconnect_via_ndjson_transport(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    scope = FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    try:
        services = build_ephemeral_fleet_compute_services(
            sample_turn,
            game_id=628580,
            perspective=1,
        )

        def replacement_loader():
            yield from iter_fleet_table_stream_events(
                sample_turn,
                (sample_turn.scores[0].ownerid,),
                game_id=628580,
                perspective=1,
                fleet_services=services,
                persistence=services.persistence,
                scheduler=scheduler,
            )

        lines = list(stream_fleet_table_ndjson(replacement_loader))
        assert len(lines) == 1
        assert json.loads(lines[0]) == {
            "type": "error",
            "detail": TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
        }
    finally:
        scheduler.end_fleet_table_stream(scope, (), stream_token=stream_token)


def test_cached_final_ledger_replays_terminal_events_without_scheduling(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    player_id = sample_turn.scores[0].ownerid
    final_persisted = PersistedFleetLedger(
        ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    services.persistence.put_ledger(
        628580,
        1,
        sample_turn.settings.turn,
        player_id,
        final_persisted,
    )

    events = _events_for_players(
        sample_turn,
        (player_id,),
        scheduler=scheduler,
        services=services,
    )
    types = [event["type"] for event in events]
    assert types == ["ledger_updated", "provenance", "complete"]
    assert events[0]["playerId"] == player_id
    assert events[0]["ledger"] == fleet_acquisition_ledger_to_json(final_persisted.ledger)
    assert events[1]["isFinal"] is True
    assert events[2]["isFinal"] is True
    assert scheduler._runs == {}


def test_multi_player_stream_emits_tagged_terminal_events(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    for player_id in player_ids:
        services.persistence.put_ledger(
            628580,
            1,
            sample_turn.settings.turn,
            player_id,
            PersistedFleetLedger(
                ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )
    events = _events_for_players(
        sample_turn,
        player_ids,
        scheduler=scheduler,
        services=services,
    )
    complete_player_ids = {
        event["playerId"]
        for event in events
        if event.get("type") == "complete" and isinstance(event.get("playerId"), int)
    }
    assert complete_player_ids == set(player_ids)


def test_player_event_ordering_provenance_before_complete(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    player_id = sample_turn.scores[0].ownerid
    services.persistence.put_ledger(
        628580,
        1,
        sample_turn.settings.turn,
        player_id,
        PersistedFleetLedger(
            ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )
    events = _events_for_players(
        sample_turn,
        (player_id,),
        scheduler=scheduler,
        services=services,
    )
    player_events = [event for event in events if event.get("playerId") == player_id]
    provenance_index = next(
        index for index, event in enumerate(player_events) if event["type"] == "provenance"
    )
    complete_index = next(
        index for index, event in enumerate(player_events) if event["type"] == "complete"
    )
    assert provenance_index < complete_index


def test_schedule_dedupes_in_flight_player_runs(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    player_id = sample_turn.scores[0].ownerid
    scope = FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    try:
        first = schedule_fleet_player_run(
            scheduler,
            turn=sample_turn,
            player_id=player_id,
            game_id=628580,
            perspective=1,
            fleet_services=services,
            persistence=services.persistence,
            stream_token=stream_token,
        )
        second = schedule_fleet_player_run(
            scheduler,
            turn=sample_turn,
            player_id=player_id,
            game_id=628580,
            perspective=1,
            fleet_services=services,
            persistence=services.persistence,
            stream_token=stream_token,
        )
        assert first is not None
        assert second is not None
        assert first.session.run_id == second.session.run_id
        assert len(scheduler._runs) == 1
        assert len(scheduler._work_queue) == 1
    finally:
        scheduler.end_fleet_table_stream(scope, (), stream_token=stream_token)


def test_tag_fleet_table_stream_event_adds_player_id():
    tagged = tag_fleet_table_stream_event(
        fleet_complete_event(is_final=True, summary="done"),
        player_id=3,
    )
    assert tagged["playerId"] == 3


def test_drain_available_multiplex_events_returns_queued_events_without_blocking():
    from api.analytics.fleet.fleet_table_player_run import FleetPlayerStreamSession

    session = FleetPlayerStreamSession(
        player_id=8,
        turn=None,  # type: ignore[arg-type]
        game_id=628580,
        perspective=1,
    )
    session.event_queue.put(fleet_complete_event(is_final=True, summary="ok"))
    row = ScheduledFleetPlayer(player_id=8, session=session)
    finished: set[str] = set()
    events = list(
        drain_available_multiplex_events(
            (row,),
            tag_player_id=True,
            finished_run_ids=finished,
        )
    )
    assert len(events) == 1
    assert events[0]["playerId"] == 8


@pytest.mark.slow
def test_concurrent_multi_player_materialization_completes(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=2)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:3])
    events = _events_for_players(sample_turn, player_ids, scheduler=scheduler)
    assert {
        event["playerId"]
        for event in events
        if event.get("type") == "complete" and isinstance(event.get("playerId"), int)
    } == set(player_ids)
