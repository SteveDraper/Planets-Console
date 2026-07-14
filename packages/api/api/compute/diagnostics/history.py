"""Shell-scoped compute step completion history ring buffer."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from api.compute.pools import ComputePriorityBand

DEFAULT_COMPLETION_HISTORY_CAP = 500

CompletionSurface = Literal["pool", "inline"]
CompletionTerminalState = Literal["success", "failed"]


@dataclass(frozen=True)
class ComputeCompletionRecord:
    """One terminal compute step execution within diagnostic scope."""

    scope_key: str
    surface: CompletionSurface
    terminal_state: CompletionTerminalState
    step_kind: str
    step_index: int
    priority_band: ComputePriorityBand
    completed_at: str
    backend: str | None = None
    duration_ms: float | None = None


class ComputeCompletionHistory:
    """Thread-safe ring buffer of completion records for one shell context."""

    def __init__(self, *, capacity: int = DEFAULT_COMPLETION_HISTORY_CAP) -> None:
        self._capacity = max(1, capacity)
        self._entries: deque[ComputeCompletionRecord] = deque(maxlen=self._capacity)
        self._lock = threading.Lock()

    def append(
        self,
        *,
        scope_key: str,
        surface: CompletionSurface,
        terminal_state: CompletionTerminalState,
        step_kind: str,
        step_index: int,
        priority_band: ComputePriorityBand,
        backend: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        record = ComputeCompletionRecord(
            scope_key=scope_key,
            surface=surface,
            terminal_state=terminal_state,
            step_kind=step_kind,
            step_index=step_index,
            priority_band=priority_band,
            completed_at=datetime.now(UTC).isoformat(),
            backend=backend,
            duration_ms=duration_ms,
        )
        with self._lock:
            self._entries.append(record)

    def recent(self) -> tuple[ComputeCompletionRecord, ...]:
        with self._lock:
            return tuple(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
