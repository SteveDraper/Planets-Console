"""Shared bounded ring buffer for shell-scoped homeworld diagnostic reports."""

from __future__ import annotations

import threading
from collections import deque
from typing import Generic, Protocol, TypeVar


class ShellScopedReport(Protocol):
    """Report shape carrying the shell context diagnostics reads filter on."""

    @property
    def game_id(self) -> int: ...

    @property
    def perspective(self) -> int: ...


TReport = TypeVar("TReport", bound=ShellScopedReport)


class ReportRing(Generic[TReport]):
    """Thread-safe process ring of reports, read newest-first per shell context."""

    def __init__(self, *, capacity: int) -> None:
        self._lock = threading.Lock()
        self._entries: deque[TReport] = deque(maxlen=capacity)

    def record(self, report: TReport) -> None:
        with self._lock:
            self._entries.append(report)

    def recent(
        self,
        *,
        game_id: int | None = None,
        perspective: int | None = None,
    ) -> tuple[TReport, ...]:
        """Newest-first reports, optionally narrowed to one shell context."""
        with self._lock:
            items = list(self._entries)
        items.reverse()
        if game_id is None and perspective is None:
            return tuple(items)
        return tuple(
            report
            for report in items
            if (game_id is None or report.game_id == game_id)
            and (perspective is None or report.perspective == perspective)
        )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


__all__ = [
    "ReportRing",
    "ShellScopedReport",
    "TReport",
]
