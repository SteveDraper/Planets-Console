"""Generation-scoped cancel fences for scores persist.

Cancel durability is separate from soft/hard stream-resolution memory (FIFO).
Fences are keyed by ``(compute scope key, execution_generation)`` so cancelled
evidence cannot land after RowRun unregister without unbounded UUID growth or
FIFO eviction races.
"""

from __future__ import annotations

import threading

from api.compute.scope import ComputeScope, format_compute_scope_key

_lock = threading.Lock()
# (scope_key, execution_generation) -> None (presence = cancelled)
_fences: dict[tuple[str, int], None] = {}
# run_id -> fence key so late persist can look up by result-wire runId
_run_id_to_fence_key: dict[str, tuple[str, int]] = {}


def mark_cancel_fence(
    scope: ComputeScope,
    execution_generation: int,
    *,
    run_id: str,
) -> None:
    """Record a cancel fence that survives RowRun unregister."""
    key = (format_compute_scope_key(scope), execution_generation)
    with _lock:
        _fences[key] = None
        _run_id_to_fence_key[run_id] = key


def is_run_cancel_fenced(run_id: str) -> bool:
    """True when ``run_id`` was cancelled under a recorded generation fence."""
    with _lock:
        key = _run_id_to_fence_key.get(run_id)
        return key is not None and key in _fences


def clear_cancel_fences() -> None:
    with _lock:
        _fences.clear()
        _run_id_to_fence_key.clear()


def reset_cancel_fence_store_for_tests() -> None:
    clear_cancel_fences()
