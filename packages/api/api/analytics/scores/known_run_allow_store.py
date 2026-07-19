"""Positive allow for finish-after-detach scores persist.

Detach unregisters the RowRun without cancelling. Late persist must still be
allowed for that known ``run_id`` -- without overloading stream-resolution FSM
``OPEN`` as a persist signal.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_allowed_run_ids: set[str] = set()


def record_known_run_allow(run_id: str) -> None:
    """Remember ``run_id`` as a known finish-after-detach persist allow."""
    with _lock:
        _allowed_run_ids.add(run_id)


def is_known_run_allowed(run_id: str) -> bool:
    with _lock:
        return run_id in _allowed_run_ids


def clear_known_run_allows() -> None:
    with _lock:
        _allowed_run_ids.clear()


def reset_known_run_allow_store_for_tests() -> None:
    clear_known_run_allows()
