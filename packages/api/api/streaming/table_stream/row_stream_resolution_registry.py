"""Process-wide bounded table of per-run stream resolutions.

Owns deliver / upgrade / silence memory and the ``multiplex_closed`` drain bit
for table-stream terminal events. Persist admission (scores) lives on
:class:`~api.analytics.military_score_inference.row_run.PersistAdmission` in
:mod:`api.analytics.scores.tier_row_run_registry` -- not here.

FIFO-bounded by ``MAX_STREAM_RESOLUTIONS``. Run IDs are unique UUIDs.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from api.streaming.table_stream.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolution,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)

MAX_STREAM_RESOLUTIONS = 4096

_lock = threading.Lock()
# Insertion order is eviction order; transitions refresh position (move-to-end).
_resolutions: OrderedDict[str, RowStreamResolution] = OrderedDict()


def _trim_locked() -> None:
    """Evict oldest resolutions until at capacity. Caller holds ``_lock``."""
    while len(_resolutions) > MAX_STREAM_RESOLUTIONS:
        _resolutions.popitem(last=False)


def _touch_locked(run_id: str, resolution: RowStreamResolution) -> None:
    """Refresh FIFO eviction order for ``run_id``. Caller holds ``_lock``."""
    _resolutions.pop(run_id, None)
    _resolutions[run_id] = resolution
    _trim_locked()


def _ensure_locked(run_id: str) -> RowStreamResolution:
    """Return existing or new OPEN resolution. Caller holds ``_lock``."""
    resolution = _resolutions.get(run_id)
    if resolution is None:
        resolution = RowStreamResolution()
    return resolution


def get_stream_resolution(run_id: str) -> RowStreamResolution | None:
    with _lock:
        return _resolutions.get(run_id)


def transition_stream_resolution(
    run_id: str,
    trigger: RowStreamResolutionTrigger,
) -> RowStreamDelivery:
    """Apply one trigger, refresh eviction order, and trim to capacity."""
    with _lock:
        resolution = _ensure_locked(run_id)
        delivery = resolution.transition(trigger)
        _touch_locked(run_id, resolution)
        return delivery


def mark_multiplex_closed(run_id: str) -> None:
    """Mark drain closed for ``run_id`` (creates OPEN resolution if missing)."""
    with _lock:
        resolution = _ensure_locked(run_id)
        resolution.multiplex_closed = True
        _touch_locked(run_id, resolution)


def seal_canceled_finish(run_id: str) -> RowStreamDelivery:
    """Internal cancel seal: FSM ``CANCELED`` + drain closed, under one lock.

    Public callers use :func:`stream_drain.seal_canceled` only. Sealing both
    sides together avoids leaving resolution ``OPEN`` with drain closed alone.
    Idempotent with a prior ``CANCELED`` transition (returns ``SILENCE``) and
    with an already-closed drain bit.
    """
    with _lock:
        resolution = _ensure_locked(run_id)
        delivery = resolution.transition(RowStreamResolutionTrigger.CANCELED)
        resolution.multiplex_closed = True
        _touch_locked(run_id, resolution)
        return delivery


def is_multiplex_closed(run_id: str) -> bool:
    """True when drain is closed for ``run_id``."""
    with _lock:
        resolution = _resolutions.get(run_id)
        return resolution is not None and resolution.multiplex_closed


def clear_multiplex_closed_if_soft(run_id: str) -> bool:
    """Clear drain-closed only while still ``SOFT_PROVISIONAL``. Returns True if cleared."""
    with _lock:
        resolution = _resolutions.get(run_id)
        if (
            resolution is None
            or resolution.state is not RowStreamResolutionState.SOFT_PROVISIONAL
            or not resolution.multiplex_closed
        ):
            return False
        resolution.multiplex_closed = False
        _touch_locked(run_id, resolution)
        return True


def discard_stream_resolution_if_state(
    run_id: str,
    state: RowStreamResolutionState,
) -> bool:
    """Compare-and-pop: remove only when still in ``state``. Returns True if removed."""
    with _lock:
        resolution = _resolutions.get(run_id)
        if resolution is None or resolution.state is not state:
            return False
        del _resolutions[run_id]
        return True


def clear_stream_resolutions() -> None:
    with _lock:
        _resolutions.clear()


def reset_stream_resolution_registry_for_tests() -> None:
    clear_stream_resolutions()
