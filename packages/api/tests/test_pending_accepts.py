"""Pending orchestrator accepts are registered, run once, and discarded."""

from __future__ import annotations

from api.streaming.table_stream.pending_accepts import PendingAccepts


def test_accept_runs_the_registered_callback_once() -> None:
    pending = PendingAccepts()
    ran: list[str] = []
    pending.register("run-1", lambda: ran.append("run-1"))

    pending.accept("run-1")
    pending.accept("run-1")

    assert ran == ["run-1"]


def test_discard_drops_the_accept() -> None:
    pending = PendingAccepts()
    ran: list[str] = []
    pending.register("run-1", lambda: ran.append("run-1"))

    pending.discard("run-1")
    pending.accept("run-1")

    assert ran == []


def test_accept_of_unknown_run_is_a_no_op() -> None:
    PendingAccepts().accept("missing")


def test_discard_all_drops_only_the_given_runs() -> None:
    pending = PendingAccepts()
    ran: list[str] = []
    pending.register("run-1", lambda: ran.append("run-1"))
    pending.register("run-2", lambda: ran.append("run-2"))

    pending.discard_all(("run-1",))
    pending.accept("run-1")
    pending.accept("run-2")

    assert ran == ["run-2"]
