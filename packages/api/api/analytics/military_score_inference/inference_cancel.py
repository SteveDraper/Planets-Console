"""Cooperative cancellation for inference row streams and tier jobs."""

from __future__ import annotations

import threading


class InferenceCancelToken:
    """Thread-safe flag checked at inference solve interrupt boundaries.

    ``is_set`` / ``wait`` match the SAT-session cancel protocol so the same
    token can drive an in-process ``stop_search`` watcher.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)
