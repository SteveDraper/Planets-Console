"""Process-wide scheduler for fleet table stream per-player materialization jobs."""

from __future__ import annotations

import os
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.fleet.fleet_table_player_run import (
    FleetPlayerStreamSession,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.errors import PlanetsConsoleError
from api.transport.fleet_table_stream import fleet_error_event

_DEFAULT_WORKER_COUNT = 4
_DEQUEUE_WAIT_SECONDS = 0.25


class TableStreamScopeAlreadyActive(PlanetsConsoleError):
    """Another NDJSON fleet table stream already owns this turn scope."""


@dataclass(frozen=True)
class FleetPlayerJob:
    session: FleetPlayerStreamSession
    materialize: Callable[[FleetPlayerStreamSession], None]


class FleetTableStreamScheduler:
    """Fair scheduler: one materialization job per player on a table stream."""

    def __init__(self, worker_count: int = _DEFAULT_WORKER_COUNT) -> None:
        self._work_queue: deque[FleetPlayerJob] = deque()
        self._runs: dict[str, FleetPlayerStreamSession] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._worker_count = worker_count
        self._workers: list[threading.Thread] = []
        self._shutdown = False
        self._active_scope: FleetTableStreamScope | None = None
        self._has_active_table_stream = False
        self._active_table_stream_token: str | None = None
        for _ in range(worker_count):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self._workers.append(thread)

    def begin_scope(self, scope: FleetTableStreamScope) -> str:
        with self._condition:
            if self._active_scope == scope and self._has_active_table_stream:
                self._preempt_active_table_stream_locked()
            elif self._active_scope != scope:
                self._invalidate_retained_state_locked()
                self._active_scope = scope
            stream_token = str(uuid.uuid4())
            self._has_active_table_stream = True
            self._active_table_stream_token = stream_token
            return stream_token

    def owns_table_stream(self, stream_token: str) -> bool:
        with self._condition:
            return self._active_table_stream_token == stream_token

    def active_scope_matches(self, scope: FleetTableStreamScope) -> bool:
        with self._condition:
            return self._active_scope == scope

    def row_run_for_player(
        self,
        scope: FleetTableStreamScope,
        player_id: int,
    ) -> FleetPlayerStreamSession | None:
        with self._condition:
            for session in self._runs.values():
                if (
                    session.game_id == scope.game_id
                    and session.perspective == scope.perspective
                    and session.turn.settings.turn == scope.turn_number
                    and session.player_id == player_id
                ):
                    return session
            return None

    def enqueue_player_run(
        self,
        session: FleetPlayerStreamSession,
        materialize: Callable[[FleetPlayerStreamSession], None],
        *,
        stream_token: str | None = None,
    ) -> FleetPlayerStreamSession | None:
        with self._condition:
            if stream_token is not None and self._active_table_stream_token != stream_token:
                return None
            for existing in self._runs.values():
                if existing.player_id == session.player_id:
                    return existing
            self._runs[session.run_id] = session
            self._work_queue.append(FleetPlayerJob(session=session, materialize=materialize))
            self._condition.notify()
            return session

    def cancel_player_run(self, run_id: str) -> None:
        with self._condition:
            session = self._runs.get(run_id)
            if session is not None:
                session.cancel_token.cancel()
            self._work_queue = deque(
                job for job in self._work_queue if job.session.run_id != run_id
            )
            self._runs.pop(run_id, None)
            self._condition.notify_all()

    def end_fleet_table_stream(
        self,
        scope: FleetTableStreamScope,
        sessions: tuple[FleetPlayerStreamSession, ...],
        *,
        stream_token: str,
    ) -> None:
        with self._condition:
            owns_scope = self._active_table_stream_token == stream_token
            for session in sessions:
                session.cancel_token.cancel()
                self._work_queue = deque(
                    job for job in self._work_queue if job.session.run_id != session.run_id
                )
                self._runs.pop(session.run_id, None)
            if owns_scope and self._active_scope == scope:
                self._has_active_table_stream = False
                self._active_table_stream_token = None
            self._condition.notify_all()

    def _preempt_active_table_stream_locked(self) -> None:
        """Cancel in-flight player runs so a reconnect can own this scope."""
        for session in self._runs.values():
            session.cancel_token.cancel()
        self._runs.clear()
        self._work_queue.clear()
        self._has_active_table_stream = False
        self._active_table_stream_token = None

    def _invalidate_retained_state_locked(self) -> None:
        self._preempt_active_table_stream_locked()

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._shutdown and not self._work_queue:
                    self._condition.wait(timeout=_DEQUEUE_WAIT_SECONDS)
                if self._shutdown:
                    return
                job = self._work_queue.popleft()
            if job.session.cancel_token.is_cancelled():
                continue
            try:
                job.materialize(job.session)
            except Exception:
                if job.session.event_queue.empty():
                    job.session.event_queue.put(
                        fleet_error_event("Fleet ledger materialization failed")
                    )
                continue
            if job.session.event_queue.empty():
                job.session.event_queue.put(
                    fleet_error_event("Fleet ledger materialization ended without stream events")
                )


_process_scheduler: FleetTableStreamScheduler | None = None
_process_scheduler_lock = threading.Lock()


def _configured_worker_count() -> int:
    raw = os.environ.get("FLEET_TABLE_STREAM_SCHEDULER_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return _DEFAULT_WORKER_COUNT


def get_fleet_table_stream_scheduler() -> FleetTableStreamScheduler:
    global _process_scheduler
    with _process_scheduler_lock:
        if _process_scheduler is None:
            _process_scheduler = FleetTableStreamScheduler(worker_count=_configured_worker_count())
        return _process_scheduler


def reset_fleet_table_stream_scheduler_for_tests() -> None:
    global _process_scheduler
    with _process_scheduler_lock:
        if _process_scheduler is not None:
            _process_scheduler._shutdown = True
            with _process_scheduler._condition:
                _process_scheduler._condition.notify_all()
        _process_scheduler = FleetTableStreamScheduler(worker_count=0)
