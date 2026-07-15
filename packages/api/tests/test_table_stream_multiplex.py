"""Unit tests for shared table-stream multiplex draining."""

from __future__ import annotations

import queue
import threading
import time

from api.streaming.table_stream.multiplex import iter_multiplexed_stream_events


class _CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


class _Session:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.event_queue: queue.Queue[dict[str, object]] = queue.Queue()
        self.cancel_token = _CancelToken()


class _Row:
    def __init__(self, player_id: int, session: _Session) -> None:
        self.player_id = player_id
        self.session = session


def test_multiplex_does_not_busy_spin_when_pending_outlives_empty_rows():
    """Mid-reschedule: pending run ids with an empty row provider must wait, not peg CPU."""
    ghost = _Session("ghost-run")
    rows_holder: list[_Row] = [_Row(1, ghost)]
    stream_active = True
    wake = threading.Event()
    iterations = {"n": 0}

    def row_provider() -> tuple[_Row, ...]:
        iterations["n"] += 1
        return tuple(rows_holder)

    def consume() -> None:
        for _ in iter_multiplexed_stream_events(
            (),
            tag_player_id=True,
            finished_run_ids=set(),
            is_stream_active=lambda: stream_active,
            row_provider=row_provider,
            wake_event=wake,
            event_to_wire_events=lambda row, event: iter((event,)),
            tag_event=lambda event, player_id: {**event, "playerId": player_id},
            multiplex_wait_seconds=0.02,
        ):
            pass

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    time.sleep(0.05)
    # Drop all rows while the ghost run id is still pending (no terminal event).
    rows_holder.clear()
    before = iterations["n"]
    time.sleep(0.15)
    after = iterations["n"]
    stream_active = False
    wake.set()
    thread.join(timeout=1.0)

    # With a 20ms wait, ~150ms of empty-rows time should be tens of iterations, not
    # hundreds of thousands from a tight continue loop.
    assert after - before < 50


def test_blocking_multiplex_marks_finished_on_terminal():
    """Regression: terminal yield must add finished_run_ids (not only discard pending).

    Table connect passes is_stream_active=owns_table_stream, so the loop keeps
    refreshing pending from finished_run_ids. Omitting finished.add after a
    complete/error leaves serverStreams open forever with idle CPU while the
    client already saw the last complete event.
    """
    session_a = _Session("run-a")
    session_b = _Session("run-b")
    rows = (_Row(1, session_a), _Row(2, session_b))
    finished: set[str] = set()
    wake = threading.Event()
    stream_active = True
    seen: list[dict[str, object]] = []

    def consume() -> None:
        for event in iter_multiplexed_stream_events(
            rows,
            tag_player_id=True,
            finished_run_ids=finished,
            is_stream_active=lambda: stream_active,
            row_provider=lambda: rows,
            wake_event=wake,
            event_to_wire_events=lambda row, event: iter((event,)),
            tag_event=lambda event, player_id: {**event, "playerId": player_id},
            multiplex_wait_seconds=0.02,
        ):
            seen.append(event)
            if len(finished) == 2:
                nonlocal_stream_stop()

    def nonlocal_stream_stop() -> None:
        nonlocal stream_active
        stream_active = False
        wake.set()

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    session_a.event_queue.put({"type": "complete", "summary": "a done"})
    session_b.event_queue.put({"type": "complete", "summary": "b done"})
    wake.set()
    thread.join(timeout=2.0)

    assert {event.get("playerId") for event in seen} == {1, 2}
    assert finished == {"run-a", "run-b"}
    assert not thread.is_alive()
