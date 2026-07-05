"""Generic round-robin multiplex drain for per-row table-stream event queues."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from typing import Protocol, TypeVar

_DEFAULT_MULTIPLEX_WAIT_SECONDS = 0.05


class MultiplexSession(Protocol):
    run_id: str
    event_queue: queue.Queue[object]
    cancel_token: object


class ScheduledStreamRow(Protocol):
    player_id: int
    session: MultiplexSession


ScheduledRowT = TypeVar("ScheduledRowT", bound=ScheduledStreamRow)


def drain_available_multiplex_events(
    rows: tuple[ScheduledRowT, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str],
    event_to_wire_events: Callable[[ScheduledRowT, object], Iterator[dict[str, object]]],
    tag_event: Callable[[dict[str, object], int], dict[str, object]] | None = None,
    terminal_types: frozenset[str] = frozenset({"complete", "error"}),
) -> Iterator[dict[str, object]]:
    """Yield any events already queued without blocking."""
    for row in rows:
        if row.session.run_id in finished_run_ids:
            continue
        while True:
            try:
                raw_event = row.session.event_queue.get_nowait()
            except queue.Empty:
                break
            for event in event_to_wire_events(row, raw_event):
                if tag_player_id and tag_event is not None:
                    event = tag_event(event, row.player_id)
                if event.get("type") in terminal_types:
                    finished_run_ids.add(row.session.run_id)
                yield event


def iter_multiplexed_stream_events(
    rows: tuple[ScheduledRowT, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str] | None = None,
    is_stream_active: Callable[[], bool] | None = None,
    row_provider: Callable[[], tuple[ScheduledRowT, ...]] | None = None,
    pending_events_provider: Callable[[], list[dict[str, object]]] | None = None,
    wake_event: threading.Event | None = None,
    event_to_wire_events: Callable[[ScheduledRowT, object], Iterator[dict[str, object]]],
    tag_event: Callable[[dict[str, object], int], dict[str, object]] | None = None,
    terminal_types: frozenset[str] = frozenset({"complete", "error"}),
    multiplex_wait_seconds: float = _DEFAULT_MULTIPLEX_WAIT_SECONDS,
) -> Iterator[dict[str, object]]:
    """Round-robin blocking reads across row event queues until rows finish.

    When ``is_stream_active`` is provided, keep waiting (including on ``wake_event``)
    while the table stream remains active so in-place row reschedule can enqueue work
    after every row has already reached a terminal event.
    """
    finished = finished_run_ids if finished_run_ids is not None else set()

    def active_rows() -> tuple[ScheduledRowT, ...]:
        if row_provider is not None:
            return row_provider()
        return rows

    def session_is_cancelled(session: MultiplexSession) -> bool:
        cancel = session.cancel_token
        is_cancelled = getattr(cancel, "is_cancelled", None)
        if callable(is_cancelled):
            return bool(is_cancelled())
        return False

    def finish_cancelled_run(row: ScheduledRowT) -> None:
        if session_is_cancelled(row.session):
            pending_run_ids.discard(row.session.run_id)
            finished.add(row.session.run_id)

    def refresh_pending_run_ids() -> set[str]:
        pending: set[str] = set()
        for row in active_rows():
            if row.session.run_id in finished:
                continue
            if session_is_cancelled(row.session):
                finished.add(row.session.run_id)
                continue
            pending.add(row.session.run_id)
        return pending

    pending_run_ids = refresh_pending_run_ids()
    cursor = 0

    def should_continue() -> bool:
        if is_stream_active is not None:
            return is_stream_active()
        return bool(pending_run_ids)

    while should_continue():
        if is_stream_active is not None and not is_stream_active():
            return
        if pending_events_provider is not None:
            for event in pending_events_provider():
                yield event
        if not pending_run_ids:
            if wake_event is not None:
                wake_event.wait(timeout=multiplex_wait_seconds)
                if wake_event.is_set():
                    wake_event.clear()
                pending_run_ids = refresh_pending_run_ids()
            continue
        current_rows = list(active_rows())
        if not current_rows:
            continue
        row = current_rows[cursor % len(current_rows)]
        cursor += 1
        if row.session.run_id not in pending_run_ids:
            continue
        if session_is_cancelled(row.session):
            finish_cancelled_run(row)
            continue
        try:
            raw_event = row.session.event_queue.get(timeout=multiplex_wait_seconds)
        except queue.Empty:
            if wake_event is not None and wake_event.is_set():
                wake_event.clear()
                pending_run_ids = refresh_pending_run_ids()
            continue
        for event in event_to_wire_events(row, raw_event):
            if event.get("type") in terminal_types:
                pending_run_ids.discard(row.session.run_id)
            if tag_player_id and tag_event is not None:
                yield tag_event(event, row.player_id)
            else:
                yield event
