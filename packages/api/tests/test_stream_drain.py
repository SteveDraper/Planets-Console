"""Unit tests for shared table-stream drain API."""

from __future__ import annotations

from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)
from api.streaming.table_stream.row_stream_resolution_registry import (
    get_stream_resolution,
    reset_stream_resolution_registry_for_tests,
    transition_stream_resolution,
)
from api.streaming.table_stream.terminal_route import TerminalRoute, route_terminal


def test_close_sets_multiplex_closed() -> None:
    reset_stream_resolution_registry_for_tests()
    try:
        stream_drain.close("run-a")
        assert stream_drain.is_closed("run-a")
    finally:
        reset_stream_resolution_registry_for_tests()


def test_reopen_if_soft_only_while_soft_provisional() -> None:
    reset_stream_resolution_registry_for_tests()
    try:
        stream_drain.close("soft-run")
        transition_stream_resolution(
            "soft-run",
            RowStreamResolutionTrigger.SOFT_PROVISIONAL,
        )
        assert stream_drain.reopen_if_soft("soft-run")
        assert not stream_drain.is_closed("soft-run")

        stream_drain.close("hard-run")
        transition_stream_resolution(
            "hard-run",
            RowStreamResolutionTrigger.DURABLE_COMPLETE,
        )
        assert not stream_drain.reopen_if_soft("hard-run")
        assert stream_drain.is_closed("hard-run")
    finally:
        reset_stream_resolution_registry_for_tests()


def test_closed_bits_remain_as_routing_history() -> None:
    """UUID run ids are never reused; closed bits are not discarded on reschedule."""
    reset_stream_resolution_registry_for_tests()
    try:
        stream_drain.close("keep-closed")
        assert stream_drain.is_closed("keep-closed")
        # Soft reopen is the only clear path, and only while soft-provisional.
        assert not stream_drain.reopen_if_soft("keep-closed")
        assert stream_drain.is_closed("keep-closed")
    finally:
        reset_stream_resolution_registry_for_tests()


def test_drain_fsm_route_matrix() -> None:
    """Shared drain×FSM cells that adapters must keep stable."""
    reset_stream_resolution_registry_for_tests()
    try:
        # Open + not closed → queue
        assert route_terminal(RowStreamDelivery.DELIVER, "a") is TerminalRoute.QUEUE
        # Soft deliver then close (multiplex/admission) → pending for later durable
        transition_stream_resolution("b", RowStreamResolutionTrigger.SOFT_PROVISIONAL)
        stream_drain.close("b")
        assert route_terminal(RowStreamDelivery.DELIVER, "b") is TerminalRoute.PENDING
        # Soft→hard upgrade always pending
        delivery = transition_stream_resolution(
            "b",
            RowStreamResolutionTrigger.DURABLE_COMPLETE,
        )
        assert delivery is RowStreamDelivery.UPGRADE
        assert route_terminal(delivery, "b") is TerminalRoute.PENDING
        # Drain-only close while OPEN → pending for orphan durable (not cancel seal)
        stream_drain.close("c")
        assert route_terminal(RowStreamDelivery.DELIVER, "c") is TerminalRoute.PENDING
        # Cancel seal: CANCELED + closed → silence late terminals
        delivery_cancel = stream_drain.seal_canceled("cancel-seal")
        assert delivery_cancel is RowStreamDelivery.SILENCE
        canceled = get_stream_resolution("cancel-seal")
        assert canceled is not None
        assert canceled.state is RowStreamResolutionState.CANCELED
        assert stream_drain.is_closed("cancel-seal")
        assert (
            transition_stream_resolution(
                "cancel-seal",
                RowStreamResolutionTrigger.DURABLE_COMPLETE,
            )
            is RowStreamDelivery.SILENCE
        )
        assert route_terminal(RowStreamDelivery.SILENCE, "cancel-seal") is TerminalRoute.SILENCE
        # Force_fresh reopen while soft
        transition_stream_resolution("d", RowStreamResolutionTrigger.SOFT_PROVISIONAL)
        stream_drain.close("d")
        assert stream_drain.reopen_if_soft("d")
        assert route_terminal(RowStreamDelivery.DELIVER, "d") is TerminalRoute.QUEUE
    finally:
        reset_stream_resolution_registry_for_tests()


def test_seal_canceled_idempotent_with_prior_canceled_transition() -> None:
    """Second seal_canceled after CANCELED is a no-op (SILENCE + closed)."""
    reset_stream_resolution_registry_for_tests()
    try:
        assert (
            transition_stream_resolution("run-x", RowStreamResolutionTrigger.CANCELED)
            is RowStreamDelivery.SILENCE
        )
        assert not stream_drain.is_closed("run-x")
        assert stream_drain.seal_canceled("run-x") is RowStreamDelivery.SILENCE
        assert stream_drain.is_closed("run-x")
        assert stream_drain.seal_canceled("run-x") is RowStreamDelivery.SILENCE
    finally:
        reset_stream_resolution_registry_for_tests()
