"""Shared assertions for table-stream ``stream_lock`` choreography."""

from __future__ import annotations

import threading


def assert_stream_lock_not_held(
    stream_lock: threading.Lock,
    *,
    message: str,
) -> None:
    """Fail if ``stream_lock`` is held (schedule must not run under the lock).

    Used by fleet/scores deadlock regressions: nested schedule/invalidation must
    observe a free lock; a failed non-blocking acquire is the 0% CPU hang fingerprint.
    """
    acquired = stream_lock.acquire(blocking=False)
    if not acquired:
        raise AssertionError(message)
    stream_lock.release()
