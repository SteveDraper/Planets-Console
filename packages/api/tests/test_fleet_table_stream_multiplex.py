"""Tests for fleet table stream multiplex connect admission."""

from __future__ import annotations

import threading
import time

import pytest
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
from api.compute.orchestrator import ComputeHandle, ComputeNodeRun, ComputeRequest
from api.transport.fleet_table_stream import (
    fleet_complete_event,
    fleet_ledger_updated_event,
)


class _AdmitOnlyOrchestrator:
    """Orchestrator stand-in: enqueue registers sessions; submit starts no work."""

    def submit(self, request: ComputeRequest) -> ComputeHandle:
        node = ComputeNodeRun(scope=request.scope, dependency_scopes=())
        return ComputeHandle(scope=request.scope, _node=node)

    def register_node_complete_listener(self, listener):
        return lambda: None


def _install_admit_only_scheduler(monkeypatch: pytest.MonkeyPatch) -> FleetTableStreamScheduler:
    """Real enqueue_player_run; stub orchestrator submit so events stay test-driven."""
    from api.compute.runtime import reset_orchestrators_for_tests

    reset_orchestrators_for_tests()
    reset_fleet_table_stream_registry_for_tests()
    reset_fleet_table_stream_scheduler_for_tests()
    scheduler = FleetTableStreamScheduler()
    stub = _AdmitOnlyOrchestrator()

    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_scheduler.orchestrator_for_context",
        lambda ctx: stub,
    )
    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_scheduler.release_orchestrator_for_context",
        lambda ctx: None,
    )
    monkeypatch.setattr(
        "api.analytics.fleet.fleet_table_stream_rows.get_fleet_table_stream_scheduler",
        lambda: scheduler,
    )
    return scheduler


def test_fleet_connect_multiplexes_progress_across_players_before_complete(
    sample_turn,
    monkeypatch,
):
    """Admit all players, then interleave progress: B emits before either complete.

    With sequential connect, player B would not even be scheduled until A's
    host-turn complete drained. Multiplex connect admits both first.
    """
    scheduler = _install_admit_only_scheduler(monkeypatch)

    player_a, player_b = (row.ownerid for row in sample_turn.scores[:2])
    player_ids = (player_a, player_b)
    services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
    )
    scope = FleetTableStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )

    events: list[dict[str, object]] = []
    stream_closed = threading.Event()

    def _collect() -> None:
        stream = iter_fleet_table_stream_events(
            sample_turn,
            player_ids,
            game_id=628580,
            perspective=1,
            fleet_services=services,
            persistence=services.persistence,
            scheduler=scheduler,
        )
        try:
            for event in stream:
                events.append(event)
        finally:
            stream_closed.set()

    thread = threading.Thread(target=_collect, daemon=True)
    thread.start()

    def _both_players_scheduled() -> bool:
        return all(
            scheduler.row_run_for_player(scope, player_id) is not None
            for player_id in player_ids
        )

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _both_players_scheduled():
            break
        time.sleep(0.01)
    else:
        raise AssertionError("both players were not admitted before timeout")

    session_a = scheduler.row_run_for_player(scope, player_a)
    session_b = scheduler.row_run_for_player(scope, player_b)
    assert session_a is not None and session_b is not None

    empty_ledger: dict[str, object] = {"ships": []}
    session_b.event_queue.put(
        fleet_ledger_updated_event(ledger={**empty_ledger, "playerId": player_b})
    )
    session_a.event_queue.put(
        fleet_ledger_updated_event(ledger={**empty_ledger, "playerId": player_a})
    )
    session_b.event_queue.put(
        fleet_complete_event(is_final=True, summary="player B done")
    )
    session_a.event_queue.put(
        fleet_complete_event(is_final=True, summary="player A done")
    )
    controller = controller_for_scope(scope)
    assert controller is not None
    controller.wake_multiplex.set()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        completes = {event.get("playerId") for event in events if event.get("type") == "complete"}
        if completes == set(player_ids):
            break
        time.sleep(0.01)
    else:
        raise AssertionError("both completes not observed before timeout")

    progress_player_ids = {
        event.get("playerId") for event in events if event.get("type") == "ledger_updated"
    }
    assert progress_player_ids == set(player_ids)

    first_complete_index = next(
        index for index, event in enumerate(events) if event.get("type") == "complete"
    )
    progress_before_first_complete = {
        event.get("playerId")
        for event in events[:first_complete_index]
        if event.get("type") == "ledger_updated"
    }
    assert progress_before_first_complete == set(player_ids)

    controller.end_stream(scheduler)
    thread.join(timeout=2.0)
    assert stream_closed.is_set()
