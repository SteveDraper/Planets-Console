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
    ready-depth cache fed by orchestrator ready-queue snapshots (absolute depths,
    not ±1 deltas). Gauge sampling reads live in-flight state via injected
    callbacks so the controller retains those collections.

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
        active_shell: Callable[[], ShellContextKey | None],
    ) -> None:
        self._timeline_capacity = timeline_capacity
        self._bound_orchestrators = bound_orchestrators
        self._in_flight_records = in_flight_records
        self._global_queue_depth = global_queue_depth
        self._configured_workers = configured_workers
        self._ancestor_turns = ancestor_turns
        self._history_for_shell = history_for_shell
        self._active_shell = active_shell
        self._timelines: dict[ShellContextKey, ComputeConcurrencyTimeline] = {}
        self._open_executions = OpenExecutionTracker()
        # Per-shell ready depth as sum of per-orchestrator contributions from
        # ready-queue-changed snapshots (complete lifecycle, no ±1 drift).
        self._ready_depth_parts: dict[ShellContextKey, dict[int, int]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._timelines.clear()
            self._ready_depth_parts.clear()
        self._open_executions.clear()

    def clear_orchestrator_ready_depth(self, orchestrator_id: int) -> None:
        """Drop one orchestrator's ready-depth contribution (unbind)."""
        with self._lock:
            empty_shells: list[ShellContextKey] = []
            for shell, parts in self._ready_depth_parts.items():
                parts.pop(orchestrator_id, None)
                if not parts:
                    empty_shells.append(shell)
            for shell in empty_shells:
                del self._ready_depth_parts[shell]

    def recent(self, shell: ShellContextKey) -> tuple:
        """Return recent concurrency timeline events for ``shell``."""
        return self._timeline_for_shell(shell).recent()

    def note_ready_queue(
        self,
        shell: ShellContextKey,
        *,
        orchestrator_id: int,
        ready_scopes: tuple[ComputeScope, ...],
    ) -> None:
        """Set one orchestrator's ready-depth contribution from a live snapshot.

        Called under the orchestrator lock (via ready-queue-changed). Must not
        call back into that orchestrator.
        """
        ancestor_turns = self._ancestor_turns(shell)
        depth = sum(
            1
            for scope in ready_scopes
            if scope_in_diagnostic_scope(
                scope,
                game_id=shell.game_id,
                perspective=shell.perspective,
                ancestor_turns=ancestor_turns,
            )
        )
        with self._lock:
            parts = self._ready_depth_parts.setdefault(shell, {})
            parts[orchestrator_id] = depth

    def note_ready_queue_for_bound_orch(
        self,
        ready_scopes: tuple[ComputeScope, ...],
        *,
        orchestrator_id: int,
        game_id: int,
        perspective: int,
    ) -> None:
        """Ready-queue-changed entry: update cache when the active shell matches."""
        shell = self._active_shell()
        if shell is None or shell.game_id != game_id or shell.perspective != perspective:
            return
        self.note_ready_queue(
            shell,
            orchestrator_id=orchestrator_id,
            ready_scopes=ready_scopes,
        )

    def bind_ready_queue_listener(
        self,
        *,
        orchestrator_id: int | None,
        game_id: int,
        perspective: int,
        fallback_id: int,
    ) -> Callable[[tuple[ComputeScope, ...]], None]:
        """Return a ready-queue-changed listener closed over one bound orchestrator."""
        resolved_id = orchestrator_id if orchestrator_id is not None else fallback_id

        def on_ready_queue_changed(ready_scopes: tuple[ComputeScope, ...]) -> None:
            self.note_ready_queue_for_bound_orch(
                ready_scopes,
                orchestrator_id=resolved_id,
                game_id=game_id,
                perspective=perspective,
            )

        return on_ready_queue_changed

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
        open_execution: bool = False,
        global_queue_depth: int | None = None,
        sample_ready_from_orchestrators: bool = False,
    ) -> None:
        """Append one lifecycle timeline event (ready / enqueue / start / inline_start)."""
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
        gauges = self._occupancy_gauges(
            shell,
            global_queue_depth=global_queue_depth,
            sample_ready_from_orchestrators=True,
        )
        timeline_kind: TimelineEventKind = "inline_complete" if surface == "inline" else "complete"
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

    def _cached_ready_depth(self, shell: ShellContextKey) -> int:
        with self._lock:
            parts = self._ready_depth_parts.get(shell)
            if not parts:
                return 0
            return sum(parts.values())

    def _occupancy_gauges(
        self,
        shell: ShellContextKey,
        *,
        global_queue_depth: int | None = None,
        sample_ready_from_orchestrators: bool = False,
    ) -> OccupancyGauges:
        """Sample occupancy gauges for a timeline event.

        Ready depth prefers the ready-queue-changed cache so pool-lock callbacks
        never nest into orchestrator locks. When ``sample_ready_from_orchestrators``
        is true (outside the pool lock), live orchestrator ready queues are used
        and the cache is refreshed to match.
        """
        ancestor_turns = self._ancestor_turns(shell)
        if sample_ready_from_orchestrators:
            ready_depth = 0
            live_parts: dict[int, int] = {}
            for bound in self._bound_orchestrators():
                if bound.game_id != shell.game_id or bound.perspective != shell.perspective:
                    continue
                view = bound.orchestrator.diagnostics_snapshot()
                orch_id = bound.orchestrator.pool_registration_id
                if orch_id is None:
                    orch_id = id(bound.orchestrator)
                part = 0
                for ready_scope in view.ready_scopes:
                    if scope_in_diagnostic_scope(
                        ready_scope,
                        game_id=shell.game_id,
                        perspective=shell.perspective,
                        ancestor_turns=ancestor_turns,
                    ):
                        part += 1
                live_parts[orch_id] = part
                ready_depth += part
            with self._lock:
                if live_parts:
                    self._ready_depth_parts[shell] = live_parts
                else:
                    self._ready_depth_parts.pop(shell, None)
        else:
            ready_depth = self._cached_ready_depth(shell)
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
