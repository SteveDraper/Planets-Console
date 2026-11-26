"""OffLockRunner: posted work runs on the runner's own thread, in order, never inline."""

from __future__ import annotations

import logging
import threading

import pytest
from api.streaming.table_stream.off_lock_runner import OffLockRunner

WAIT_SECONDS = 2.0
THREAD_NAME = "test-off-lock-runner"


class _Recorder:
    """Records each item's label and thread, and lets a test wait for a count."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self.labels: list[str] = []
        self.threads: list[threading.Thread] = []

    def item(self, label: str):
        def run() -> None:
            with self._condition:
                self.labels.append(label)
                self.threads.append(threading.current_thread())
                self._condition.notify_all()

        return run

    def wait_for(self, count: int) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: len(self.labels) >= count, WAIT_SECONDS)


def _runner_thread_alive() -> bool:
    return any(thread.name == THREAD_NAME for thread in threading.enumerate())


def _wait_until(condition) -> bool:
    deadline = threading.Event()
    for _ in range(int(WAIT_SECONDS / 0.01)):
        if condition():
            return True
        deadline.wait(0.01)
    return condition()


@pytest.fixture
def runner():
    runner = OffLockRunner(thread_name=THREAD_NAME)
    yield runner
    runner.shutdown()


def test_posted_work_runs_in_order_on_the_runner_thread(runner) -> None:
    recorder = _Recorder()
    runner.ensure_started()

    for label in ("a", "b", "c"):
        runner.post(recorder.item(label))

    assert recorder.wait_for(3)
    assert recorder.labels == ["a", "b", "c"]
    assert {thread.name for thread in recorder.threads} == {THREAD_NAME}


def test_work_posted_before_start_is_kept_and_runs_after_start(runner) -> None:
    recorder = _Recorder()
    runner.post(recorder.item("early"))

    assert recorder.labels == []
    runner.ensure_started()

    assert recorder.wait_for(1)
    assert recorder.labels == ["early"]


def test_post_returns_while_the_caller_holds_a_lock_the_work_needs(runner) -> None:
    lock = threading.Lock()
    recorder = _Recorder()
    item = recorder.item("locked")

    def needs_the_lock() -> None:
        with lock:
            item()

    runner.ensure_started()
    with lock:
        runner.post(needs_the_lock)
        assert recorder.labels == []

    assert recorder.wait_for(1)


def test_drain_waits_for_work_posted_before_it(runner) -> None:
    release = threading.Event()
    recorder = _Recorder()
    runner.ensure_started()
    runner.post(lambda: release.wait(WAIT_SECONDS))
    runner.post(recorder.item("after"))

    assert runner.drain(timeout=0.1) is False
    release.set()

    assert runner.drain(timeout=WAIT_SECONDS) is True
    assert recorder.labels == ["after"]


def test_drain_with_no_live_thread_returns_at_once(runner) -> None:
    assert runner.drain(timeout=WAIT_SECONDS) is True

    runner.post(lambda: None)

    assert runner.drain(timeout=WAIT_SECONDS) is False


def test_drain_on_the_runner_thread_returns_false_at_once(runner) -> None:
    outcomes: list[bool] = []
    runner.ensure_started()

    runner.post(lambda: outcomes.append(runner.drain(timeout=WAIT_SECONDS)))

    assert runner.drain(timeout=WAIT_SECONDS) is True
    assert outcomes == [False]


def test_an_item_that_raises_is_logged_and_the_next_one_runs(runner, caplog) -> None:
    recorder = _Recorder()
    runner.ensure_started()

    def raises() -> None:
        raise RuntimeError("item failed")

    with caplog.at_level(logging.ERROR):
        runner.post(raises)
        runner.post(recorder.item("next"))
        assert recorder.wait_for(1)

    assert any("item failed" in record.getMessage() or record.exc_info for record in caplog.records)


def test_a_base_exception_ends_the_thread_and_the_backlog_resumes_on_the_next_start(
    runner, caplog
) -> None:
    recorder = _Recorder()
    blocked = threading.Event()
    runner.ensure_started()

    def interrupt() -> None:
        blocked.wait(WAIT_SECONDS)
        raise KeyboardInterrupt

    with caplog.at_level(logging.ERROR):
        runner.post(interrupt)
        runner.post(recorder.item("kept"))
        blocked.set()
        assert _wait_until(lambda: not _runner_thread_alive())

    assert recorder.labels == []
    assert caplog.records
    runner.ensure_started()

    assert recorder.wait_for(1)
    assert recorder.labels == ["kept"]


def test_shutdown_drains_then_stops(runner) -> None:
    recorder = _Recorder()
    runner.ensure_started()
    runner.post(recorder.item("before-shutdown"))

    runner.shutdown()

    assert recorder.labels == ["before-shutdown"]
    assert not _runner_thread_alive()


def test_shutdown_of_a_never_started_runner_returns_at_once() -> None:
    runner = OffLockRunner(thread_name=THREAD_NAME)

    runner.shutdown(timeout=WAIT_SECONDS)

    assert runner.drain(timeout=WAIT_SECONDS) is True
