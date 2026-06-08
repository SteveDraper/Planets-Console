"""Cooperative cancellation for inference row streams and tier jobs."""

from __future__ import annotations

import threading


class InferenceCancelToken:
    """Thread-safe flag checked at inference solve interrupt boundaries."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()
