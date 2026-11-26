"""Shared doubles for table-stream connect tests."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

import pytest
from api.streaming.table_stream.connect import AdmissionDispatch
from api.streaming.table_stream.off_lock_runner import OffLockRunner
from api.streaming.table_stream.stream_scheduler import TableStreamScheduler


def end_stream_inline(scheduler: TableStreamScheduler, controller: object) -> None:
    """End a controller's stream on the calling thread, as the off-lock runner would.

    For tests that drive a controller without a connect generator; the caller
    must hold no lock the end takes.
    """
    scheduler.end_table_stream(controller.scope, controller.stream_token)


STREAM_END_WAIT_SECONDS = 2.0


def wait_for_stream_ends(scheduler: TableStreamScheduler) -> None:
    """Wait until every stream end posted to the scheduler's off-lock runner has run."""
    assert scheduler.off_lock_runner.drain(timeout=STREAM_END_WAIT_SECONDS)


class RecordingTableStreamScheduler:
    """A ``TableStreamScheduler`` that hands out tokens and records each end.

    Ends run on its real off-lock runner, so a test drains the runner before it
    reads ``ended``. Shut it down when the test ends.
    """

    def __init__(self, token: str = "token") -> None:
        self.off_lock_runner = OffLockRunner(thread_name="test-table-stream-off-lock")
        self._token = token
        self.begun: list[object] = []
        self.ended: list[tuple[object, str]] = []

    def begin_scope(self, scope: object) -> str:
        self.begun.append(scope)
        return self._token

    def end_table_stream(self, scope: object, stream_token: str, /) -> None:
        self.ended.append((scope, stream_token))

    def shutdown(self) -> None:
        self.off_lock_runner.shutdown()


class IdleConnectPolicy:
    """A connect policy with no preamble and no players: the stream opens and idles.

    Records ``attach`` and ``detach``; ``detach`` raises when built with
    ``detach_error``.
    """

    def __init__(self, *, detach_error: BaseException | None = None) -> None:
        self.attached = False
        self.detached = False
        self._detach_error = detach_error
        self._wake = threading.Event()

    def preamble_events(self) -> tuple[dict[str, object], ...]:
        return ({"type": "open"},)

    def attach(self) -> None:
        self.attached = True

    def detach(self) -> None:
        self.detached = True
        if self._detach_error is not None:
            raise self._detach_error

    def owns_table_stream(self) -> bool:
        return True

    def resolve_admission(self, player_id: int) -> object:
        raise AssertionError("an idle stream admits no player")

    def dispatch_admission(self, player_id: int, admission: object) -> AdmissionDispatch[object]:
        raise AssertionError("an idle stream admits no player")

    def current_scheduled_rows(self) -> tuple[object, ...]:
        return ()

    def register_scheduled_row(self, player_id: int, scheduled: object) -> None:
        raise AssertionError("an idle stream admits no player")

    def adopt_admission_scheduled_row(self, player_id: int, scheduled: object) -> bool:
        raise AssertionError("an idle stream admits no player")

    def drain_pending_wire_events(self) -> list[dict[str, object]]:
        return []

    def wake_multiplex(self) -> threading.Event:
        return self._wake

    def multiplex_event_to_wire_events(
        self, row: object, raw_event: object
    ) -> Iterator[dict[str, object]]:
        return iter(())

    def tag_event(self, event: dict[str, object], player_id: int) -> dict[str, object]:
        return event

    def terminal_types(self) -> frozenset[str]:
        return frozenset()


@pytest.fixture
def make_recording_table_stream_scheduler() -> Iterator[
    Callable[[str], RecordingTableStreamScheduler]
]:
    """Build ``RecordingTableStreamScheduler``s that are shut down when the test ends."""
    built: list[RecordingTableStreamScheduler] = []

    def make(token: str = "token") -> RecordingTableStreamScheduler:
        scheduler = RecordingTableStreamScheduler(token)
        built.append(scheduler)
        return scheduler

    yield make
    for scheduler in built:
        scheduler.shutdown()
