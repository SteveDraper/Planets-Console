"""Concurrency timeline recording for compute diagnostics."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from api.compute.diagnostics.bindings import BoundOrchestrator
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.history import (
    CompletionSurface,
    CompletionTerminalState,
    ComputeCompletionHistory,
)
from api.compute.diagnostics.in_flight import InFlightPoolExecution
from api.compute.diagnostics.scope import scope_in_diagnostic_scope
from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.diagnostics.timeline import (
    ComputeConcurrencyTimeline,
    OccupancyGauges,
    OpenExecutionTracker,
    TimelineEventKind,
    format_execution_key,
    make_concurrency_event,
)
from api.compute.orchestrator import ComputeNodeRun
from api.compute.pools import ComputePriorityBand
from api.compute.scope import ComputeScope


class ConcurrencyTimelineRecorder:
    """Records occupancy gauges and concurrency timeline events for one controller.

    Owns shell-scoped timeline rings, the open-execution duration tracker, and the
    ready-depth shadow counter. Gauge sampling reads live in-flight / orchestrator
    state via injected callbacks so the controller retains those collections.

    Lock order: this recorder's lock must never be held while acquiring a callback
    that takes the controller lock *after* the controller already holds its lock
    and is calling into the recorder. Callers must release the controller lock
    before ``record`` / ``record_finish`` (pool dequeue already does this).
    """

    def __init__(
        self,
        *,
        timeline_capacity: Callable[[], int],
        bound_orchestrators: Callable[[], tuple[BoundOrchestrator, ...]],
        in_flight_records: Callable[[], Sequence[InFlightPoolExecution]],
        global_queue_depth: Callable[[], int],
        configured_workers: Callable[[], int],
        ancestor_turns: Callable[[ShellContextKey], frozenset[int]],
        history_for_shell: Callable[[ShellContextKey], ComputeCompletionHistory],
    ) -> None:
        self._timeline_capacity = timeline_capacity
        self._bound_orchestrators = bound_orchestrators
        self._in_flight_records = in_flight_records
        self._global_queue_depth = global_queue_depth
        self._configured_workers = configured_workers
        self._ancestor_turns = ancestor_turns
        self._history_for_shell = history_for_shell
        self._timelines: dict[ShellContextKey, ComputeConcurrencyTimeline] = {}
        self._open_executions = OpenExecutionTracker()
        self._ready_depth_by_shell: dict[ShellContextKey, int] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._timelines.clear()
            self._ready_depth_by_shell.clear()
        self._open_executions.clear()

    def recent(self, shell: ShellContextKey) -> tuple:
        """Return recent concurrency timeline events for ``shell``."""
        return self._timeline_for_shell(shell).recent()

    def record(
        self,
        shell: ShellContextKey,
        *,
        kind: TimelineEventKind,
        scope: ComputeScope,
        orchestrator_id: int | None,
        step_kind: str | None,
        step_index: int,
        priority_band: ComputePriorityBand | None = None,
        backend: str | None = None,
        ready_depth_delta: int = 0,
        open_execution: bool = False,
        global_queue_depth: int | None = None,
        sample_ready_from_orchestrators: bool = False,
    ) -> None:
        """Append one lifecycle timeline event (ready / enqueue / start / inline_start)."""
        if ready_depth_delta:
            self._adjust_ready_depth(shell, ready_depth_delta)
        scope_key = format_compute_scope_key(scope)
        execution_key = format_execution_key(
            orchestrator_id=orchestrator_id,
            scope_key=scope_key,
            step_kind=step_kind or "",
            step_index=step_index,
        )
        if open_execution:
            self._open_executions.open(execution_key, backend=backend)
        gauges = self._occupancy_gauges(
            shell,
            global_queue_depth=global_queue_depth,
            sample_ready_from_orchestrators=sample_ready_from_orchestrators,
        )
        self._append(
            shell,
            kind=kind,
            scope_key=scope_key,
            execution_key=execution_key,
            gauges=gauges,
            step_kind=step_kind,
            step_index=step_index,
            priority_band=priority_band,
            backend=backend,
        )

    def record_finish(
        self,
        shell: ShellContextKey,
        *,
        scope: ComputeScope,
        node: ComputeNodeRun,
        step_kind: str,
        surface: CompletionSurface,
        terminal_state: CompletionTerminalState,
        orchestrator_id: int | None,
        backend: str | None,
        global_queue_depth: int | None = None,
    ) -> None:
        """One finish sink: timeline complete/inline_complete + completion history."""
        scope_key = format_compute_scope_key(scope)
        execution_key = format_execution_key(
            orchestrator_id=orchestrator_id,
            scope_key=scope_key,
            step_kind=step_kind,
            step_index=node.step_index,
        )
        duration_ms, opened_backend = self._open_executions.close(execution_key)
        resolved_backend = backend if backend is not None else opened_backend
        gauges = self._occupancy_gauges(shell, global_queue_depth=global_queue_depth)
        timeline_kind: TimelineEventKind = (
            "inline_complete" if surface == "inline" else "complete"
        )
        self._append(
            shell,
            kind=timeline_kind,
            scope_key=scope_key,
            execution_key=execution_key,
            gauges=gauges,
            step_kind=step_kind,
            step_index=node.step_index,
            priority_band=node.priority_band,
            backend=resolved_backend,
            terminal_state=terminal_state,
            duration_ms=duration_ms,
        )
        self._history_for_shell(shell).append(
            scope_key=scope_key,
            surface=surface,
            terminal_state=terminal_state,
            step_kind=step_kind,
            step_index=node.step_index,
            priority_band=node.priority_band,
            backend=resolved_backend,
            duration_ms=duration_ms,
        )

    def _timeline_for_shell(self, shell: ShellContextKey) -> ComputeConcurrencyTimeline:
        with self._lock:
            timeline = self._timelines.get(shell)
            if timeline is None:
                timeline = ComputeConcurrencyTimeline(capacity=self._timeline_capacity())
                self._timelines[shell] = timeline
            return timeline

    def _adjust_ready_depth(self, shell: ShellContextKey, delta: int) -> None:
        with self._lock:
            next_depth = max(0, self._ready_depth_by_shell.get(shell, 0) + delta)
            self._ready_depth_by_shell[shell] = next_depth

    def _occupancy_gauges(
        self,
        shell: ShellContextKey,
        *,
        global_queue_depth: int | None = None,
        sample_ready_from_orchestrators: bool = False,
    ) -> OccupancyGauges:
        """Sample occupancy gauges for a timeline event.

        Ready depth prefers the ready-event counter so pool-lock callbacks never
        nest into orchestrator locks. When ``sample_ready_from_orchestrators`` is
        true (outside the pool lock), the live orchestrator ready queues are used
        instead.
        """
        ancestor_turns = self._ancestor_turns(shell)
        if sample_ready_from_orchestrators:
            ready_depth = 0
            for bound in self._bound_orchestrators():
                if bound.game_id != shell.game_id or bound.perspective != shell.perspective:
                    continue
                view = bound.orchestrator.diagnostics_snapshot()
                for ready_scope in view.ready_scopes:
                    if scope_in_diagnostic_scope(
                        ready_scope,
                        game_id=shell.game_id,
                        perspective=shell.perspective,
                        ancestor_turns=ancestor_turns,
                    ):
                        ready_depth += 1
        else:
            with self._lock:
                ready_depth = self._ready_depth_by_shell.get(shell, 0)
        in_flight = self._in_flight_records()
        scoped_in_flight = sum(
            1
            for record in in_flight
            if scope_in_diagnostic_scope(
                record.scope,
                game_id=shell.game_id,
                perspective=shell.perspective,
                ancestor_turns=ancestor_turns,
            )
        )
        global_in_flight = len(in_flight)
        if global_queue_depth is None:
            global_queue_depth = self._global_queue_depth()
        return OccupancyGauges(
            scoped_ready_depth=ready_depth,
            scoped_in_flight_count=scoped_in_flight,
            global_in_flight_count=global_in_flight,
            global_queue_depth=global_queue_depth,
            configured_workers=self._configured_workers(),
        )

    def _append(
        self,
        shell: ShellContextKey,
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
    ) -> None:
        self._timeline_for_shell(shell).append(
            make_concurrency_event(
                kind=kind,
                scope_key=scope_key,
                execution_key=execution_key,
                gauges=gauges,
                step_kind=step_kind,
                step_index=step_index,
                priority_band=priority_band,
                backend=backend,
                terminal_state=terminal_state,
                duration_ms=duration_ms,
            )
        )
