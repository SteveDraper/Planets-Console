"""Shell-scoped compute concurrency timeline ring buffer."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from api.compute.orchestrator_observers import LifecycleEventKind
from api.compute.priority_band import ComputePriorityBand
from api.compute.scope import format_compute_scope_key
from api.compute.step_execution_key import StepExecutionKey

DEFAULT_TIMELINE_CAPACITY = 5000

# Occupancy / scheduling events recorded by the concurrency timeline.
OccupancyTimelineEventKind = Literal[
    "ready",
    "enqueue",
    "start",
    "complete",
    "inline_start",
    "inline_complete",
]
# Occupancy plus causal lifecycle kinds owned by orchestrator observers.
TimelineEventKind = OccupancyTimelineEventKind | LifecycleEventKind


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
    # Optional causal payload for restart / abort / stale-finish events.
    detail: dict[str, object] | None = None


def format_execution_key(step: StepExecutionKey) -> str:
    """Return the wire label naming ``step`` on every timeline event about it."""
    orch = "none" if step.orchestrator_id is None else str(step.orchestrator_id)
    scope_key = format_compute_scope_key(step.scope)
    return f"{orch}|{scope_key}|g{step.execution_generation}|{step.step_kind}|{step.step_index}"


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


@dataclass(frozen=True)
class OpenExecution:
    """What a start event recorded, kept until the matching finish.

    ``priority_band`` is the band the step started at (for a pool step, the
    band it was picked at), so its finish reports that band.
    """

    started_at: datetime
    backend: str | None
    priority_band: ComputePriorityBand


@dataclass(frozen=True)
class ClosedExecution:
    """A finished execution paired with its start event."""

    duration_ms: float
    backend: str | None
    priority_band: ComputePriorityBand


class OpenExecutionTracker:
    """Process-local map of open start events for duration pairing."""

    def __init__(self) -> None:
        self._open: dict[StepExecutionKey, OpenExecution] = {}
        self._lock = threading.Lock()

    def open(
        self,
        step: StepExecutionKey,
        *,
        backend: str | None,
        priority_band: ComputePriorityBand,
        started_at: datetime | None = None,
    ) -> datetime:
        started = started_at if started_at is not None else datetime.now(UTC)
        with self._lock:
            self._open[step] = OpenExecution(
                started_at=started,
                backend=backend,
                priority_band=priority_band,
            )
        return started

    def close(self, step: StepExecutionKey) -> ClosedExecution | None:
        """Return the closed execution, or None when no matching start was recorded."""
        with self._lock:
            opened = self._open.pop(step, None)
        if opened is None:
            return None
        return ClosedExecution(
            duration_ms=(datetime.now(UTC) - opened.started_at).total_seconds() * 1000.0,
            backend=opened.backend,
            priority_band=opened.priority_band,
        )

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
    detail: dict[str, object] | None = None,
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
        detail=detail,
    )
