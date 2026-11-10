"""Live table-stream stand-ins for on-walk submission tests."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from concurrent.futures import Future
from dataclasses import dataclass

from api.analytics.on_walk_live import _pending_on_walks
from api.analytics.turn_roster import iter_turn_players
from api.compute.orchestrator import ComputeOrchestrator

SUBMIT_TIMEOUT_SECONDS = 5.0


class _EventQueue:
    def __init__(self) -> None:
        self.events: list[object] = []

    def put(self, event: object) -> None:
        self.events.append(event)


@dataclass
class _QueuedSession:
    event_queue: _EventQueue


@dataclass
class _QueuedRow:
    session: _QueuedSession


class LiveStream:
    """Typed stand-in for a fleet or inference table-stream controller."""

    def __init__(self, turn, ctx, player_ids: list[int]) -> None:
        self.turn = turn
        self.query_context = ctx
        self.player_ids = tuple(player_ids)
        self.scheduled_rows = {
            player_id: _QueuedRow(session=_QueuedSession(event_queue=_EventQueue()))
            for player_id in player_ids
        }
        self.wake_multiplex = threading.Event()

    def emit_work_accepted(self, player_id: int) -> None:
        row = self.scheduled_rows.get(player_id)
        if row is None:
            return
        row.session.event_queue.put({"type": "work_accepted"})
        self.wake_multiplex.set()

    def accepted_events(self, player_id: int) -> list[object]:
        return self.scheduled_rows[player_id].session.event_queue.events


def roster_player_ids(turn) -> list[int]:
    return [player.id for player in iter_turn_players(turn)]


def attach_stream(registry, scope, turn, ctx, player_ids: list[int]) -> LiveStream:
    controller = LiveStream(turn, ctx, player_ids)
    registry.attach(scope, controller)
    return controller


def recording_orchestrator(monkeypatch) -> tuple[ComputeOrchestrator, list]:
    orchestrator = ComputeOrchestrator(compute_registry={})
    submitted: list = []

    def record(request):
        submitted.append(request)

    monkeypatch.setattr(orchestrator, "submit", record)
    return orchestrator, submitted


def wait_for_submits(futures: Iterable[Future[None]]) -> None:
    """Wait until every player's background on-walk submit has ended."""
    for future in futures:
        future.result(timeout=SUBMIT_TIMEOUT_SECONDS)


def wait_for_unblocked_submits(
    orchestrator: ComputeOrchestrator, futures: Iterable[Future[None]]
) -> None:
    """Wait for every submit except those still behind an off-setting walk."""
    waiting = {waiter.submitted for waiter in _pending_on_walks(orchestrator).waiters.values()}
    wait_for_submits(future for future in futures if future not in waiting)
