"""Shared assertions for table-stream lock choreography."""

from __future__ import annotations

import threading


def assert_lock_not_held(
    lock: threading.Lock,
    *,
    message: str,
) -> None:
    """Fail if ``lock`` is held (nested work must not run under the lock).

    Used by fleet/scores deadlock regressions: nested schedule/invalidation or
    persistence I/O must observe a free lock; a failed non-blocking acquire is
    the 0% CPU hang fingerprint.
    """
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise AssertionError(message)
    lock.release()


def assert_stream_lock_not_held(
    stream_lock: threading.Lock,
    *,
    message: str,
) -> None:
    """Fail if ``stream_lock`` is held (schedule must not run under the lock)."""
    assert_lock_not_held(stream_lock, message=message)
