"""Live table-stream stand-ins for on-walk submission tests."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from api.analytics.turn_roster import iter_turn_players
from api.compute.orchestrator import ComputeOrchestrator


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
