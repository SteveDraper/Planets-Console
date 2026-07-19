"""Process-wide bounded table of per-run soft/hard stream resolutions.

Owns deliver / upgrade / silence memory for table-stream terminal events only.
Cancel durability lives in :mod:`api.analytics.scores.cancel_fence_store`
(generation-scoped). Finish-after-detach persist allow lives in
:mod:`api.analytics.scores.known_run_allow_store`.

FIFO-bounded by ``MAX_STREAM_RESOLUTIONS``. Soft/hard terminals are short-lived
relative to this capacity. Run IDs are unique UUIDs.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from api.analytics.military_score_inference.row_stream_resolution import (
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


def get_stream_resolution(run_id: str) -> RowStreamResolution | None:
    with _lock:
        return _resolutions.get(run_id)


def transition_stream_resolution(
    run_id: str,
    trigger: RowStreamResolutionTrigger,
) -> RowStreamDelivery:
    """Apply one trigger, refresh eviction order, and trim to capacity."""
    with _lock:
        resolution = _resolutions.get(run_id)
        if resolution is None:
            resolution = RowStreamResolution()
        delivery = resolution.transition(trigger)
        _touch_locked(run_id, resolution)
        return delivery


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
