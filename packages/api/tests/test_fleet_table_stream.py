"""Tests for the multiplexed fleet table NDJSON stream."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from api.analytics.fleet.chain import ensure_fleet_baseline, ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_services import (
    FleetComputeServices,
    build_ephemeral_fleet_compute_services,
)
from api.analytics.fleet.fleet_table_player_run import (
    _initial_wire_before_ledger,
    wire_ledger_progress_events,
)
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
from api.analytics.fleet.gap_fill_coordinator import reset_coordinators
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import (
    fleet_acquisition_ledger_to_json,
)
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.analytics.turn_roster import iter_turn_players
from api.serialization.turn import turn_info_from_json
from api.storage.memory_asset import MemoryAssetBackend
from api.transport.fleet_table_stream import (
    fleet_complete_event,
    stream_fleet_table_ndjson,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture(autouse=True)
def _reset_fleet_gap_fill_coordinators():
    reset_coordinators()
    yield
    reset_coordinators()


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        turn_rst = json.load(handle)
        backend.put("games/628580/1/turns/111", turn_rst)
        turn_110 = copy.deepcopy(turn_rst)
        turn_110["settings"]["turn"] = 110
        turn_110["game"]["turn"] = 110
        backend.put("games/628580/1/turns/110", turn_110)
        turn_112 = copy.deepcopy(turn_rst)
        turn_112["settings"]["turn"] = 112
        turn_112["game"]["turn"] = 112
        backend.put("games/628580/1/turns/112", turn_112)
    return backend


@pytest.fixture
def persistence(memory_backend):
    return FleetSnapshotPersistenceService(memory_backend)


@pytest.fixture
def load_turn(memory_backend):
    def _load(turn_number: int):
        key = f"games/628580/1/turns/{turn_number}"
        try:
            data = memory_backend.get(key)
        except Exception:
            return None
        if data is None:
            return None
        return turn_info_from_json(data)

    return _load


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
        assert first_event.get("type") != "error"
    finally:
        second.close()


def test_fleet_table_stream_reconnect_preempts_active_scope(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    scope = FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    first_token = scheduler.begin_scope(scope)
    second_token = scheduler.begin_scope(scope)

    assert second_token != first_token
    assert not scheduler.owns_table_stream(first_token)
    assert scheduler.owns_table_stream(second_token)

    scheduler.end_fleet_table_stream(scope, (), stream_token=second_token)


def test_fleet_table_stream_reconnect_via_ndjson_transport(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)
    scope = FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    first_token = scheduler.begin_scope(scope)
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

    def replacement_loader():
        yield from iter_fleet_table_stream_events(
            sample_turn,
            (player_id,),
            game_id=628580,
            perspective=1,
            fleet_services=services,
            persistence=services.persistence,
            scheduler=scheduler,
        )

    lines: list[str] = []
    for line in stream_fleet_table_ndjson(replacement_loader):
        lines.append(line)
        payload = json.loads(line)
        if payload.get("type") == "complete":
            break

    assert lines
    assert not scheduler.owns_table_stream(first_token)


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


def test_gap_fill_stream_emits_incremental_ledger_updates_before_complete(
    persistence,
    load_turn,
):
    """Gap-fill M..N emits ledger_updated after each leg, then complete."""
    turn_110 = load_turn(110)
    assert turn_110 is not None
    turn_112 = load_turn(112)
    assert turn_112 is not None
    player_id = turn_112.scores[0].ownerid

    persistence.put_snapshot(
        628580,
        1,
        110,
        ensure_fleet_baseline(628580, 1, turn_110),
    )

    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=1)
    services = FleetComputeServices(
        persistence=persistence,
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
    )

    events = _events_for_players(
        turn_112,
        (player_id,),
        scheduler=scheduler,
        services=services,
    )
    player_events = [event for event in events if event.get("playerId") == player_id]
    ledger_updates = [event for event in player_events if event.get("type") == "ledger_updated"]
    complete_events = [event for event in player_events if event.get("type") == "complete"]

    assert len(ledger_updates) >= 2
    assert len(complete_events) == 1
    assert complete_events[0]["type"] == "complete"
    first_records = ledger_updates[0]["ledger"]["records"]
    assert isinstance(first_records, list)
    assert len(first_records) > 0
    complete_index = player_events.index(complete_events[0])
    assert all(player_events.index(event) < complete_index for event in ledger_updates)


def test_wire_ledger_progress_events_use_host_turn_roster_names(sample_turn):
    from dataclasses import replace

    turn_111 = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=111),
        game=replace(sample_turn.game, turn=111),
    )
    player_id = turn_111.scores[0].ownerid
    baseline = ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id)
    persisted = PersistedFleetLedger(
        ledger=baseline,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=False,
            prior_ledger_at_n_minus_1=True,
        ),
    )

    events = wire_ledger_progress_events(
        before=None,
        persisted=persisted,
        host_turn=turn_111,
    )

    ledger_event = next(event for event in events if event["type"] == "ledger_updated")
    expected_name = next(
        player.username for player in iter_turn_players(turn_111) if player.id == player_id
    )
    assert ledger_event["ledger"]["playerName"] == expected_name


def test_initial_wire_before_ledger_shapes_cached_host_turn(sample_turn, persistence):
    from dataclasses import replace

    turn_111 = replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=111),
        game=replace(sample_turn.game, turn=111),
    )
    player_id = turn_111.scores[0].ownerid
    baseline = ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id)
    stale_ledger = replace(baseline, player_name="stale-name")
    before_persisted = PersistedFleetLedger(
        ledger=stale_ledger,
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )

    result = _initial_wire_before_ledger(
        persistence=persistence,
        game_id=628580,
        perspective=1,
        player_id=player_id,
        host_turn=turn_111,
        before_persisted=before_persisted,
    )

    expected_name = next(
        player.username for player in iter_turn_players(turn_111) if player.id == player_id
    )
    assert result is not None
    assert result.player_name == expected_name


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


def test_materialization_job_emits_complete_after_progress_when_session_cancelled(
    persistence,
    load_turn,
):
    """A cancelled session still receives complete after successful gap-fill."""
    from unittest.mock import patch

    from api.analytics.fleet.chain import ensure_fleet_baseline, ensure_fleet_baseline_for_player
    from api.analytics.fleet.compute_services import FleetComputeServices
    from api.analytics.fleet.fleet_table_player_run import (
        FleetPlayerStreamSession,
        run_fleet_player_materialization_job,
    )
    from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger

    turn_110 = load_turn(110)
    assert turn_110 is not None
    persistence.put_snapshot(628580, 1, 110, ensure_fleet_baseline(628580, 1, turn_110))

    turn_112 = load_turn(112)
    assert turn_112 is not None
    player_id = turn_112.scores[0].ownerid

    session = FleetPlayerStreamSession(
        player_id=player_id,
        turn=turn_112,
        game_id=628580,
        perspective=1,
    )
    services = FleetComputeServices(
        persistence=persistence,
        game_id=628580,
        perspective=1,
        load_turn=load_turn,
    )
    final_persisted = PersistedFleetLedger(
        ledger=ensure_fleet_baseline_for_player(628580, 1, turn_112, player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )

    def materialize_with_cancel(*args, on_progress=None, **kwargs):
        if on_progress is not None:
            on_progress(final_persisted, 112)
        session.cancel_token.cancel()
        return final_persisted

    with patch(
        "api.analytics.fleet.fleet_table_player_run.get_or_materialize_fleet_ledger_for_player",
        side_effect=materialize_with_cancel,
    ):
        run_fleet_player_materialization_job(
            session,
            fleet_services=services,
            persistence=persistence,
        )

    events: list[dict[str, object]] = []
    while not session.event_queue.empty():
        events.append(session.event_queue.get_nowait())

    assert [event.get("type") for event in events if event.get("type") == "ledger_updated"]
    assert events[-1]["type"] == "complete"


@pytest.mark.slow
def test_concurrent_multi_player_materialization_completes(sample_turn):
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=2)
    player_ids = tuple(player.id for player in list(iter_turn_players(sample_turn))[:3])
    events = _events_for_players(sample_turn, player_ids, scheduler=scheduler)
    assert {
        event["playerId"]
        for event in events
        if event.get("type") == "complete" and isinstance(event.get("playerId"), int)
    } == set(player_ids)
