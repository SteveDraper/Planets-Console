"""OffLockWaker: wakes run a callback on its own thread, never inline and never blocking."""

from __future__ import annotations

import logging
import threading
import time

import pytest
from api.streaming.table_stream.off_lock_waker import OffLockWaker

WAIT_SECONDS = 2.0


class _RecordingCallback:
    """Counts calls, records the calling thread and lets a test wait for a call count."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self.call_count = 0
        self.threads: list[threading.Thread] = []

    def __call__(self) -> None:
        with self._condition:
            self.call_count += 1
            self.threads.append(threading.current_thread())
            self._condition.notify_all()

    def wait_for_calls(self, count: int) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self.call_count >= count, WAIT_SECONDS)


@pytest.fixture
def recording_waker():
    callback = _RecordingCallback()
    waker = OffLockWaker(callback, thread_name="test-off-lock-waker")
    yield waker, callback
    waker.shutdown()


def test_a_wake_runs_the_callback_on_the_waker_thread(recording_waker) -> None:
    waker, callback = recording_waker
    waker.ensure_started()

    waker.wake()

    assert callback.wait_for_calls(1)
    assert callback.threads[0] is not threading.current_thread()


def test_each_wake_runs_the_callback(recording_waker) -> None:
    waker, callback = recording_waker
    waker.ensure_started()

    for _ in range(3):
        waker.wake()

    assert callback.wait_for_calls(3)


def test_wake_returns_while_the_caller_holds_a_lock_the_callback_needs() -> None:
    lock = threading.Lock()
    callback = _RecordingCallback()

    def callback_needing_the_lock() -> None:
        with lock:
            callback()

    waker = OffLockWaker(callback_needing_the_lock, thread_name="test-off-lock-waker")
    waker.ensure_started()
    try:
        with lock:
            waker.wake()
            assert callback.call_count == 0
        assert callback.wait_for_calls(1)
    finally:
        waker.shutdown()


def test_a_raising_callback_is_logged_and_later_wakes_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    callback = _RecordingCallback()
    should_raise = [True]

    def flaky_callback() -> None:
        callback()
        if should_raise[0]:
            should_raise[0] = False
            raise RuntimeError("callback failed")

    waker = OffLockWaker(flaky_callback, thread_name="test-off-lock-waker")
    waker.ensure_started()
    try:
        with caplog.at_level(logging.ERROR, logger="api.streaming.table_stream.off_lock_waker"):
            waker.wake()
            assert callback.wait_for_calls(1)
            waker.wake()
            assert callback.wait_for_calls(2)
        failure_texts = [record.exc_text or "" for record in caplog.records]
        assert any("callback failed" in text for text in failure_texts)
    finally:
        waker.shutdown()


def test_a_wake_before_start_does_nothing(recording_waker) -> None:
    waker, callback = recording_waker

    waker.wake()
    waker.ensure_started()

    time.sleep(0.05)
    assert callback.call_count == 0


def test_a_wake_after_shutdown_does_nothing(recording_waker) -> None:
    waker, callback = recording_waker
    waker.ensure_started()
    waker.shutdown()

    waker.wake()

    time.sleep(0.05)
    assert callback.call_count == 0


def test_a_restart_after_shutdown_runs_wakes_on_a_new_thread(recording_waker) -> None:
    waker, callback = recording_waker
    waker.ensure_started()
    waker.wake()
    assert callback.wait_for_calls(1)
    waker.shutdown()

    waker.ensure_started()
    waker.wake()

    assert callback.wait_for_calls(2)
    assert callback.threads[1] is not callback.threads[0]


def test_ensure_started_twice_keeps_one_thread(recording_waker) -> None:
    waker, callback = recording_waker
    waker.ensure_started()
    waker.wake()
    assert callback.wait_for_calls(1)

    waker.ensure_started()
    waker.wake()

    assert callback.wait_for_calls(2)
    assert callback.threads[1] is callback.threads[0]


def test_shutdown_from_the_callback_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    finished = threading.Event()
    holder: list[OffLockWaker] = []

    def shut_down_from_inside() -> None:
        holder[0].shutdown()
        finished.set()

    waker = OffLockWaker(shut_down_from_inside, thread_name="test-off-lock-waker")
    holder.append(waker)
    waker.ensure_started()
    with caplog.at_level(logging.ERROR, logger="api.streaming.table_stream.off_lock_waker"):
        waker.wake()
        assert finished.wait(WAIT_SECONDS)
    assert not caplog.records
