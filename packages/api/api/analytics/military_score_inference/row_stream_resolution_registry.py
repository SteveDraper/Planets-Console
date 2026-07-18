"""Process-wide bounded table of per-run stream resolutions.

Single store for post-RowRun memory: soft/hard terminals and cancel
(``CANCELED``). Shared by the inference scheduler (stream delivery) and scores
persist (``is_row_run_cancelled``) so cancel fences are not a parallel encoding.

FIFO-bounded by ``MAX_STREAM_RESOLUTIONS``. Capacity eviction is an accepted
risk for very long-lived processes -- late-persist and late-peer races are
short relative to this capacity. Run IDs are unique UUIDs.
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

# Same capacity rationale as the former cancel-fence bound.
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


def is_stream_resolution_canceled(run_id: str) -> bool:
    """True when ``run_id`` is remembered as ``CANCELED`` (cancel fence)."""
    with _lock:
        resolution = _resolutions.get(run_id)
        return (
            resolution is not None and resolution.state is RowStreamResolutionState.CANCELED
        )


def mark_stream_resolution_canceled(run_id: str) -> None:
    """Set ``CANCELED`` that survives RowRun unregister (cancel fence).

    Production cancel goes through
    ``InferenceStreamTeardownMixin._apply_cancel_intent_locked``, which
    transitions to ``CANCELED`` before unregister. Call this directly only for
    fence-capacity tests. Detach must not set ``CANCELED``.

    Re-marking the same ``run_id`` refreshes its eviction order.
    """
    transition_stream_resolution(run_id, RowStreamResolutionTrigger.CANCELED)


def reset_stream_resolution_registry_for_tests() -> None:
    clear_stream_resolutions()
