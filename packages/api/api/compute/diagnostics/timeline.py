"""Shell-scoped compute concurrency timeline ring buffer."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from api.compute.pools import ComputePriorityBand

DEFAULT_TIMELINE_CAPACITY = 5000

TimelineEventKind = Literal[
    "ready",
    "enqueue",
    "start",
    "complete",
    "inline_start",
    "inline_complete",
]


@dataclass(frozen=True)
class OccupancyGauges:
    """Point-in-time occupancy sampled when a timeline event is recorded."""

    scoped_ready_depth: int
    scoped_in_flight_count: int
    global_in_flight_count: int
    global_queue_depth: int
    configured_workers: int


@dataclass(frozen=True)
class ComputeConcurrencyEvent:
    """One schedulable orchestration event in the concurrency timeline."""

    kind: TimelineEventKind
    timestamp: str
    scope_key: str
    step_kind: str | None
    step_index: int | None
    priority_band: ComputePriorityBand | None
    backend: str | None
    execution_key: str
    terminal_state: str | None
    duration_ms: float | None
    gauges: OccupancyGauges


def format_execution_key(
    *,
    orchestrator_id: int | None,
    scope_key: str,
    step_kind: str,
    step_index: int,
) -> str:
    """Return a stable execution key for start/complete duration pairing."""
    orch = "none" if orchestrator_id is None else str(orchestrator_id)
    return f"{orch}|{scope_key}|{step_kind}|{step_index}"


class ComputeConcurrencyTimeline:
    """Thread-safe ring buffer of concurrency events for one shell context."""

    def __init__(self, *, capacity: int = DEFAULT_TIMELINE_CAPACITY) -> None:
        self._capacity = max(1, capacity)
        self._entries: deque[ComputeConcurrencyEvent] = deque(maxlen=self._capacity)
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def append(self, event: ComputeConcurrencyEvent) -> None:
        with self._lock:
            self._entries.append(event)

    def recent(self) -> tuple[ComputeConcurrencyEvent, ...]:
        with self._lock:
            return tuple(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


@dataclass
class OpenExecution:
    """In-flight start timestamp used to derive wall duration on finish."""

    started_at: datetime
    backend: str | None


class OpenExecutionTracker:
    """Process-local map of open start events for duration pairing."""

    def __init__(self) -> None:
        self._open: dict[str, OpenExecution] = {}
        self._lock = threading.Lock()

    def open(
        self,
        execution_key: str,
        *,
        backend: str | None,
        started_at: datetime | None = None,
    ) -> datetime:
        started = started_at if started_at is not None else datetime.now(UTC)
        with self._lock:
            self._open[execution_key] = OpenExecution(started_at=started, backend=backend)
        return started

    def close(self, execution_key: str) -> tuple[float | None, str | None]:
        """Return ``(duration_ms, backend)`` when a matching start exists."""
        with self._lock:
            opened = self._open.pop(execution_key, None)
        if opened is None:
            return None, None
        duration_ms = (datetime.now(UTC) - opened.started_at).total_seconds() * 1000.0
        return duration_ms, opened.backend

    def clear(self) -> None:
        with self._lock:
            self._open.clear()


def make_concurrency_event(
    *,
    kind: TimelineEventKind,
    scope_key: str,
    execution_key: str,
    gauges: OccupancyGauges,
    step_kind: str | None = None,
    step_index: int | None = None,
    priority_band: ComputePriorityBand | None = None,
    backend: str | None = None,
    terminal_state: str | None = None,
    duration_ms: float | None = None,
    timestamp: datetime | None = None,
) -> ComputeConcurrencyEvent:
    """Build one timeline event with a UTC ISO timestamp."""
    stamped = timestamp if timestamp is not None else datetime.now(UTC)
    return ComputeConcurrencyEvent(
        kind=kind,
        timestamp=stamped.isoformat(),
        scope_key=scope_key,
        step_kind=step_kind,
        step_index=step_index,
        priority_band=priority_band,
        backend=backend,
        execution_key=execution_key,
        terminal_state=terminal_state,
        duration_ms=duration_ms,
        gauges=gauges,
    )
