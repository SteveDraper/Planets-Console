"""Unit tests for shared table-stream drain API."""

from __future__ import annotations

import threading

from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_stream_resolution import RowStreamResolutionTrigger
from api.streaming.table_stream.row_stream_resolution_registry import (
    is_multiplex_closed,
    reset_stream_resolution_registry_for_tests,
    transition_stream_resolution,
)


class _FakeController:
    def __init__(self) -> None:
        self.finished_run_ids: set[str] = set()
        self.stream_lock = threading.Lock()


def test_close_sets_finished_and_multiplex_closed() -> None:
    reset_stream_resolution_registry_for_tests()
    try:
        controller = _FakeController()
        stream_drain.close(controller, "run-a")
        assert "run-a" in controller.finished_run_ids
        assert is_multiplex_closed("run-a")
    finally:
        reset_stream_resolution_registry_for_tests()


def test_reopen_if_soft_only_while_soft_provisional() -> None:
    reset_stream_resolution_registry_for_tests()
    try:
        controller = _FakeController()
        stream_drain.close(controller, "soft-run")
        transition_stream_resolution(
            "soft-run",
            RowStreamResolutionTrigger.SOFT_PROVISIONAL,
        )
        assert stream_drain.reopen_if_soft(controller, "soft-run")
        assert "soft-run" not in controller.finished_run_ids
        assert not is_multiplex_closed("soft-run")

        stream_drain.close(controller, "hard-run")
        transition_stream_resolution(
            "hard-run",
            RowStreamResolutionTrigger.DURABLE_COMPLETE,
        )
        assert not stream_drain.reopen_if_soft(controller, "hard-run")
        assert "hard-run" in controller.finished_run_ids
        assert is_multiplex_closed("hard-run")
    finally:
        reset_stream_resolution_registry_for_tests()


def test_discard_and_clear_only_touch_finished_set() -> None:
    reset_stream_resolution_registry_for_tests()
    try:
        controller = _FakeController()
        stream_drain.close(controller, "keep-closed")
        stream_drain.discard(controller, "keep-closed")
        assert "keep-closed" not in controller.finished_run_ids
        assert is_multiplex_closed("keep-closed")

        stream_drain.close(controller, "cleared")
        stream_drain.clear(controller)
        assert not controller.finished_run_ids
        assert is_multiplex_closed("cleared")
    finally:
        reset_stream_resolution_registry_for_tests()


def test_drain_fsm_route_matrix() -> None:
    """Shared drain×FSM cells that adapters must keep stable."""
    from api.streaming.table_stream.row_stream_resolution import RowStreamDelivery
    from api.streaming.table_stream.terminal_route import TerminalRoute, route_terminal

    reset_stream_resolution_registry_for_tests()
    try:
        controller = _FakeController()
        # Open + not closed → queue
        assert route_terminal(RowStreamDelivery.DELIVER, "a") is TerminalRoute.QUEUE
        # Soft deliver then close (multiplex/admission) → pending for later durable
        transition_stream_resolution("b", RowStreamResolutionTrigger.SOFT_PROVISIONAL)
        stream_drain.close(controller, "b")
        assert route_terminal(RowStreamDelivery.DELIVER, "b") is TerminalRoute.PENDING
        # Soft→hard upgrade always pending
        delivery = transition_stream_resolution(
            "b",
            RowStreamResolutionTrigger.DURABLE_COMPLETE,
        )
        assert delivery is RowStreamDelivery.UPGRADE
        assert route_terminal(delivery, "b") is TerminalRoute.PENDING
        # Cancel-silent close while OPEN → pending for orphan durable
        stream_drain.close(controller, "c")
        assert route_terminal(RowStreamDelivery.DELIVER, "c") is TerminalRoute.PENDING
        # Force_fresh reopen while soft
        transition_stream_resolution("d", RowStreamResolutionTrigger.SOFT_PROVISIONAL)
        stream_drain.close(controller, "d")
        assert stream_drain.reopen_if_soft(controller, "d")
        assert route_terminal(RowStreamDelivery.DELIVER, "d") is TerminalRoute.QUEUE
    finally:
        reset_stream_resolution_registry_for_tests()
