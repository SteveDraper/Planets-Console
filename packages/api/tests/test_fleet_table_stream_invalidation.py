"""Integration tests for fleet table stream invalidation and in-place reschedule."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.fleet_table_stream_registry import (
    controller_for_scope,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_rows import iter_fleet_table_stream_events
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    reset_fleet_table_stream_scheduler_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from api.transport.fleet_table_stream import fleet_complete_event

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        backend.put("games/628580/1/turns/111", json.load(handle))
    return backend


def _install_workerless_scheduler(monkeypatch: pytest.MonkeyPatch) -> FleetTableStreamScheduler:
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler(worker_count=0)

    def _get_scheduler() -> FleetTableStreamScheduler:
        return scheduler

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_rows.get_fleet_table_stream_scheduler",
        _get_scheduler,
    )
    return scheduler


def _stream_scope(sample_turn) -> FleetTableStreamScope:
    return FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def _end_open_fleet_table_stream(
    scope: FleetTableStreamScope,
    scheduler: FleetTableStreamScheduler,
) -> None:
    controller = controller_for_scope(scope)
    if controller is not None:
        controller.end_stream(scheduler)


def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def _run_ids_for_players(
    scheduler: FleetTableStreamScheduler,
    player_ids: tuple[int, ...],
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for session in scheduler._runs.values():
        if session.player_id in player_ids:
            mapping[session.player_id] = session.run_id
    return mapping


def _seed_cached_ledgers(
    persistence: FleetSnapshotPersistenceService,
    sample_turn,
    *,
    turn_number: int,
    player_ids: tuple[int, ...],
) -> None:
    for player_id in player_ids:
        persistence.put_ledger(
            628580,
            1,
            turn_number,
            player_id,
            PersistedFleetLedger(
                ledger=ensure_fleet_baseline_for_player(628580, 1, sample_turn, player_id),
                provenance=FleetMaterializationProvenance(
                    turn_evidence_at_n=True,
                    prior_ledger_at_n_minus_1=True,
                ),
            ),
        )


def test_all_cached_replay_keeps_stream_open_for_evidence_invalidation_integration(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """After every player replays from cache, evidence invalidation reschedules on the open stream."""
    reset_fleet_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    fleet_persistence = services.persistence
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=fleet_persistence,
    )
    _seed_cached_ledgers(
        fleet_persistence,
        sample_turn,
        turn_number=turn_number,
        player_ids=player_ids,
    )

    stream = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=fleet_persistence,
        scheduler=scheduler,
    )
    events: list[dict[str, object]] = []
    stream_closed = threading.Event()
    scope = _stream_scope(sample_turn)

    def consume_stream() -> None:
        try:
            for event in stream:
                events.append(event)
        finally:
            stream.close()
            stream_closed.set()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()

    _wait_until(
        lambda: sum(1 for event in events if event.get("type") == "complete") >= len(player_ids)
    )
    assert len(scheduler._runs) == 0
    assert not stream_closed.is_set()
    assert controller_for_scope(scope) is not None

    target_player_id, other_player_id = player_ids
    invalidation.on_inference_evidence_updated(628580, 1, turn_number, target_player_id)

    _wait_until(lambda: target_player_id in _run_ids_for_players(scheduler, player_ids))
    assert other_player_id not in _run_ids_for_players(scheduler, (other_player_id,))
    assert fleet_persistence.get_ledger(628580, 1, turn_number, target_player_id) is None

    rescheduled_run = scheduler._runs[_run_ids_for_players(scheduler, player_ids)[target_player_id]]
    rescheduled_run.event_queue.put(
        fleet_complete_event(
            is_final=True,
            summary="after evidence invalidation on cached row",
        )
    )

    _wait_until(
        lambda: any(
            event.get("type") == "complete"
            and event.get("playerId") == target_player_id
            and event.get("summary") == "after evidence invalidation on cached row"
            for event in events
        )
    )
    cached_other_events = [
        event
        for event in events
        if event.get("type") == "complete"
        and event.get("playerId") == other_player_id
        and event.get("summary") == "Fleet ledger loaded from cache."
    ]
    assert len(cached_other_events) == 1

    _end_open_fleet_table_stream(scope, scheduler)
    thread.join(timeout=2.0)


def test_evidence_invalidation_reschedules_player_on_open_stream_integration(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Integration: invalidation while iter_fleet_table_stream_events multiplex is active."""
    reset_fleet_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    fleet_persistence = services.persistence
    inference_persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(
        inference_persistence,
        fleet_persistence=fleet_persistence,
    )
    _seed_cached_ledgers(
        fleet_persistence,
        sample_turn,
        turn_number=turn_number,
        player_ids=player_ids,
    )

    stream = iter_fleet_table_stream_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        fleet_services=services,
        persistence=fleet_persistence,
        scheduler=scheduler,
    )

    def consume_stream() -> None:
        try:
            for _event in stream:
                pass
        finally:
            stream.close()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()
    _wait_until(
        lambda: controller_for_scope(_stream_scope(sample_turn)) is not None
        and len(scheduler._runs) == 0
    )

    target_player_id, other_player_id = player_ids
    before = _run_ids_for_players(scheduler, player_ids)
    assert before == {}

    invalidation.on_inference_evidence_updated(628580, 1, turn_number, target_player_id)

    _wait_until(lambda: target_player_id in _run_ids_for_players(scheduler, player_ids))
    after = _run_ids_for_players(scheduler, player_ids)
    assert other_player_id not in after
    assert fleet_persistence.get_ledger(628580, 1, turn_number, target_player_id) is None

    _end_open_fleet_table_stream(_stream_scope(sample_turn), scheduler)
    thread.join(timeout=2.0)
