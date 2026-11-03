"""One pending orchestrator accept per table-stream run.

Fleet and scores enqueue register the accept here. Connect yields every
player's paint, then accepts; reschedule and export ensure accept immediately.
Cancel discards the accept so a late call does not submit.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable


class PendingAccepts:
    """Run-id map of accepts that have not been run or discarded.

    ``register`` and ``discard`` may run while the caller holds its scheduler
    lock. ``accept`` pops under this lock, releases it, then runs the callback,
    so the callback can take the scheduler lock without inverting lock order.
    """

    def __init__(self) -> None:
        self._accept_by_run_id: dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()

    def register(self, run_id: str, accept: Callable[[], None]) -> None:
        with self._lock:
            self._accept_by_run_id[run_id] = accept

    def accept(self, run_id: str) -> None:
        with self._lock:
            pending = self._accept_by_run_id.pop(run_id, None)
        if pending is not None:
            pending()

    def discard(self, run_id: str) -> None:
        with self._lock:
            self._accept_by_run_id.pop(run_id, None)

    def discard_all(self, run_ids: Iterable[str]) -> None:
        with self._lock:
            for run_id in run_ids:
                self._accept_by_run_id.pop(run_id, None)
