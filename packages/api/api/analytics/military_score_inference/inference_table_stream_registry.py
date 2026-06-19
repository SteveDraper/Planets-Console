"""Registry for the active scores inference table stream (in-place reschedule)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.models.game import TurnInfo

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_stream_rows import ScheduledInferenceRow


class TableStreamRowScheduler(Protocol):
    def schedule_row(self, player_id: int) -> ScheduledInferenceRow | None: ...


@dataclass
class ActiveInferenceTableStream:
    scope: InferenceStreamScope
    stream_token: str
    turn: TurnInfo
    player_ids: tuple[int, ...]
    scheduled_rows: dict[int, ScheduledInferenceRow]
    finished_run_ids: set[str]
    schedule_row: Callable[[int], ScheduledInferenceRow | None]
    cancel_row: Callable[[int], None]
    wake_multiplex: Callable[[], None]
    lock: threading.Lock = field(default_factory=threading.Lock)


_registry_lock = threading.Lock()
_active_stream: ActiveInferenceTableStream | None = None


def attach_inference_table_stream(stream: ActiveInferenceTableStream) -> None:
    global _active_stream
    with _registry_lock:
        _active_stream = stream


def detach_inference_table_stream(stream_token: str) -> None:
    global _active_stream
    with _registry_lock:
        if _active_stream is not None and _active_stream.stream_token == stream_token:
            _active_stream = None


def _active_stream_for_scope(scope: InferenceStreamScope) -> ActiveInferenceTableStream | None:
    with _registry_lock:
        if _active_stream is None or _active_stream.scope != scope:
            return None
        return _active_stream


def reschedule_inference_row(scope: InferenceStreamScope, player_id: int) -> bool:
    """Cancel and reschedule one row on the open table stream for ``scope``."""
    stream = _active_stream_for_scope(scope)
    if stream is None:
        return False
    with stream.lock:
        old_row = stream.scheduled_rows.pop(player_id, None)
        if old_row is not None:
            stream.finished_run_ids.discard(old_row.session.run_id)
            stream.cancel_row(player_id)
        scheduled = stream.schedule_row(player_id)
        if scheduled is None:
            return False
        stream.scheduled_rows[player_id] = scheduled
        stream.finished_run_ids.discard(scheduled.session.run_id)
    stream.wake_multiplex()
    return True


def reschedule_all_inference_rows(scope: InferenceStreamScope) -> bool:
    """Cancel and reschedule every row on the open table stream for ``scope``."""
    stream = _active_stream_for_scope(scope)
    if stream is None:
        return False
    with stream.lock:
        for player_id in stream.player_ids:
            stream.cancel_row(player_id)
        stream.finished_run_ids.clear()
        stream.scheduled_rows.clear()
        for player_id in stream.player_ids:
            scheduled = stream.schedule_row(player_id)
            if scheduled is not None:
                stream.scheduled_rows[player_id] = scheduled
    stream.wake_multiplex()
    return True


def reset_inference_table_stream_registry_for_tests() -> None:
    global _active_stream
    with _registry_lock:
        _active_stream = None
