"""Sole writer for table-stream drain closed state.

Updates controller ``finished_run_ids`` and the shared resolution
``multiplex_closed`` bit together. Adapters and multiplex must not mutate
``finished_run_ids`` directly.
"""

from __future__ import annotations

import threading
from collections.abc import MutableSet
from typing import Protocol

from api.streaming.table_stream.row_stream_resolution_registry import (
    clear_multiplex_closed_if_soft,
    mark_multiplex_closed,
)


class _DrainController(Protocol):
    finished_run_ids: MutableSet[str]
    stream_lock: threading.Lock


def close(controller: _DrainController, run_id: str) -> None:
    """Mark ``run_id`` drain-closed for multiplex and terminal routing."""
    with controller.stream_lock:
        controller.finished_run_ids.add(run_id)
    mark_multiplex_closed(run_id)


def close_unlocked(finished_run_ids: MutableSet[str], run_id: str) -> None:
    """Close drain when the caller already holds ``controller.stream_lock``.

    Also used by multiplex, which owns the finished set without a controller lock.
    """
    finished_run_ids.add(run_id)
    mark_multiplex_closed(run_id)


def reopen_if_soft(controller: _DrainController, run_id: str) -> bool:
    """Re-open drain only while resolution is still soft-provisional.

    Returns True when drain was reopened (caller should wake multiplex).
    """
    if not clear_multiplex_closed_if_soft(run_id):
        return False
    with controller.stream_lock:
        controller.finished_run_ids.discard(run_id)
    return True


def discard(controller: _DrainController, run_id: str) -> None:
    """Drop finished membership for a replaced / rescheduled run_id.

    Does not clear ``multiplex_closed`` on the process registry (UUID run ids are
    never reused). Used when adopting a new scheduled row for the same player.
    """
    with controller.stream_lock:
        controller.finished_run_ids.discard(run_id)


def discard_unlocked(finished_run_ids: MutableSet[str], run_id: str) -> None:
    """Discard finished membership when the caller already holds the stream lock."""
    finished_run_ids.discard(run_id)


def clear(controller: _DrainController) -> None:
    """Clear all finished membership for a controller (reschedule-all)."""
    with controller.stream_lock:
        controller.finished_run_ids.clear()


def clear_unlocked(finished_run_ids: MutableSet[str]) -> None:
    """Clear finished membership when the caller already holds the stream lock."""
    finished_run_ids.clear()
