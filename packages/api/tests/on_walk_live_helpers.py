"""Live table-stream stand-ins for on-walk submission tests."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterable
from concurrent.futures import Future
from dataclasses import dataclass, field

from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.on_walk_live import _pending_on_walks
from api.analytics.turn_roster import iter_turn_players
from api.compute.orchestrator import ComputeOrchestrator
from api.streaming.table_stream.registry_catalog import TableStreamScopeBinding

SUBMIT_TIMEOUT_SECONDS = 5.0


class _EventQueue:
    def __init__(self) -> None:
        self.events: list[object] = []

    def put(self, event: object) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class _QueuedSession:
    """One row's session: its stream identity, run id, and event queue."""

    player_id: int
    game_id: int
    perspective: int
    turn_number: int
    event_queue: _EventQueue = field(default_factory=_EventQueue)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class _QueuedRow:
    session: _QueuedSession


class LiveStream:
    """Typed stand-in for a fleet or inference table-stream controller.

    Calls the compute side makes on an open stream are recorded in order:
    ``rescheduled_player_ids`` for ``reschedule_row`` and ``delivered_events``
    for ``deliver_domain_event``.
    """

    def __init__(self, scope: TableStreamScopeBinding, turn, ctx, player_ids: list[int]) -> None:
        self.stream_token = uuid.uuid4().hex
        self.turn = turn
        self.query_context = ctx
        self.player_ids = tuple(player_ids)
        self.scheduled_rows = {
            player_id: _QueuedRow(
                session=_QueuedSession(
                    player_id=player_id,
                    game_id=scope.game_id,
                    perspective=scope.perspective,
                    turn_number=scope.turn_number,
                )
            )
            for player_id in player_ids
        }
        self.wake_multiplex = threading.Event()
        self.rescheduled_player_ids: list[int] = []
        self.delivered_events: list[tuple[int, object]] = []

    def reschedule_row(self, player_id: int) -> bool:
        """Record a row reschedule; the row stays scheduled, as a successful re-admit leaves it."""
        self.rescheduled_player_ids.append(player_id)
        self.wake_multiplex.set()
        return True

    def deliver_domain_event(
        self, session: _QueuedSession | InferenceRowStreamSession, event: object
    ) -> None:
        """Record a domain event delivered to ``session``'s row and wake the multiplex."""
        self.delivered_events.append((session.player_id, event))
        self.wake_multiplex.set()

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


def attach_stream(
    registry, scope: TableStreamScopeBinding, turn, ctx, player_ids: list[int]
) -> LiveStream:
    controller = LiveStream(scope, turn, ctx, player_ids)
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
