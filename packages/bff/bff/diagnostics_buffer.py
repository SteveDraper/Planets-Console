"""MRU (most-recent) circular buffer of serialized diagnostic trees (thread-safe)."""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

_buffer: "DiagnosticsBuffer | None" = None
_buffer_lock = threading.Lock()


class DiagnosticsBuffer:
    def __init__(self, maxlen: int) -> None:
        self._lock = threading.Lock()
        self._maxlen = max(0, maxlen)
        self._items: deque[dict[str, Any]] = (
            deque(maxlen=self._maxlen) if self._maxlen > 0 else deque()
        )

    def reconfigure(self, maxlen: int) -> None:
        with self._lock:
            self._maxlen = max(0, maxlen)
            if self._maxlen == 0:
                self._items = deque()
                return
            self._items = deque(self._items, maxlen=self._maxlen)

    def append(self, summary: str, tree: dict[str, Any]) -> None:
        if self._maxlen <= 0:
            return
        rec = {
            "capturedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "summary": summary,
            "diagnostics": tree,
        }
        with self._lock:
            self._items.append(rec)

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)


def get_diagnostics_buffer() -> DiagnosticsBuffer:
    global _buffer
    with _buffer_lock:
        if _buffer is None:
            from bff.config import get_config

            _buffer = DiagnosticsBuffer(get_config().diagnostics_buffer_size)
        return _buffer


def reconfigure_diagnostics_buffer(maxlen: int) -> None:
    """Resize or (re)create the process-global buffer. Called from :func:`bff.config.set_config`."""
    global _buffer
    with _buffer_lock:
        if _buffer is None:
            _buffer = DiagnosticsBuffer(maxlen)
        else:
            _buffer.reconfigure(maxlen)
