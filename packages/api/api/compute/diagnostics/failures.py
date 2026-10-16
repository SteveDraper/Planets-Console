"""Shell-scoped ring of recent compute-node failures for diagnostics snapshots."""

from __future__ import annotations

import threading
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

DEFAULT_FAILURE_LOG_CAP = 20
_TRACEBACK_MAX_CHARS = 8_000
_MESSAGE_MAX_CHARS = 2_000


@dataclass(frozen=True)
class ComputeFailureRecord:
    """One failed compute node, including the exception that settled it.

    Dependency failures are included. They carry the original exception, so
    the traceback points at the step that raised, and ``scope_key`` names the
    node that was failed because of it.
    """

    scope_key: str
    step_kind: str | None
    step_index: int | None
    exception_type: str
    message: str
    traceback: str
    failed_at: str


class ComputeFailureLog:
    """Thread-safe ring of the most recent node failures for one shell."""

    def __init__(self, *, capacity: int = DEFAULT_FAILURE_LOG_CAP) -> None:
        self._capacity = max(1, capacity)
        self._entries: deque[ComputeFailureRecord] = deque(maxlen=self._capacity)
        self._lock = threading.Lock()

    def append(
        self,
        *,
        scope_key: str,
        step_kind: str | None,
        step_index: int | None,
        error: BaseException,
    ) -> None:
        record = ComputeFailureRecord(
            scope_key=scope_key,
            step_kind=step_kind,
            step_index=step_index,
            exception_type=type(error).__name__,
            message=_exception_message(error),
            traceback=_exception_traceback(error),
            failed_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            self._entries.append(record)

    def recent(self) -> tuple[ComputeFailureRecord, ...]:
        with self._lock:
            return tuple(self._entries)


def _exception_message(error: BaseException) -> str:
    message = str(error)
    if len(message) <= _MESSAGE_MAX_CHARS:
        return message
    return message[:_MESSAGE_MAX_CHARS]


def _exception_traceback(error: BaseException) -> str:
    text = "".join(traceback.format_exception(error))
    if len(text) <= _TRACEBACK_MAX_CHARS:
        return text
    return text[-_TRACEBACK_MAX_CHARS:]
