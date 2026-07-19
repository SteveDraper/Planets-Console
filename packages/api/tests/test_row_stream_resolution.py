"""Unit tests for shared table-stream row resolution and terminal routing."""

from api.streaming.table_stream.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolution,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)
from api.streaming.table_stream.row_stream_resolution_registry import (
    clear_multiplex_closed_if_soft,
    is_multiplex_closed,
    mark_multiplex_closed,
    reset_stream_resolution_registry_for_tests,
    transition_stream_resolution,
)
from api.streaming.table_stream.terminal_route import TerminalRoute, route_terminal


def test_soft_provisional_upgrades_to_hard_complete() -> None:
    resolution = RowStreamResolution()

    assert (
        resolution.transition(RowStreamResolutionTrigger.SOFT_PROVISIONAL)
        is RowStreamDelivery.DELIVER
    )
    assert resolution.state is RowStreamResolutionState.SOFT_PROVISIONAL
    assert (
        resolution.transition(RowStreamResolutionTrigger.DURABLE_COMPLETE)
        is RowStreamDelivery.UPGRADE
    )
    assert resolution.state is RowStreamResolutionState.HARD_TERMINAL


def test_hard_terminal_silences_later_peer_failure() -> None:
    resolution = RowStreamResolution()

    resolution.transition(RowStreamResolutionTrigger.DURABLE_COMPLETE)

    assert (
        resolution.transition(RowStreamResolutionTrigger.DURABLE_FAILURE)
        is RowStreamDelivery.SILENCE
    )
    assert resolution.state is RowStreamResolutionState.HARD_TERMINAL


def test_soft_provisional_delivers_later_durable_failure() -> None:
    resolution = RowStreamResolution()

    resolution.transition(RowStreamResolutionTrigger.SOFT_PROVISIONAL)

    assert (
        resolution.transition(RowStreamResolutionTrigger.DURABLE_FAILURE)
        is RowStreamDelivery.DELIVER
    )
    assert resolution.state is RowStreamResolutionState.HARD_TERMINAL


def test_missed_admission_replaces_provisional_claim_with_failure() -> None:
    resolution = RowStreamResolution()

    resolution.transition(RowStreamResolutionTrigger.SOFT_PROVISIONAL)

    assert (
        resolution.transition(RowStreamResolutionTrigger.ADMISSION_MISSED)
        is RowStreamDelivery.DELIVER
    )
    assert resolution.state is RowStreamResolutionState.HARD_TERMINAL


def test_cancel_silences_later_delivery() -> None:
    resolution = RowStreamResolution()

    assert resolution.transition(RowStreamResolutionTrigger.CANCELED) is RowStreamDelivery.SILENCE
    assert resolution.state is RowStreamResolutionState.CANCELED
    assert (
        resolution.transition(RowStreamResolutionTrigger.DURABLE_COMPLETE)
        is RowStreamDelivery.SILENCE
    )


def test_multiplex_closed_independent_of_fsm_state() -> None:
    reset_stream_resolution_registry_for_tests()
    try:
        mark_multiplex_closed("open-closed")
        assert is_multiplex_closed("open-closed")
        transition_stream_resolution(
            "open-closed",
            RowStreamResolutionTrigger.SOFT_PROVISIONAL,
        )
        assert is_multiplex_closed("open-closed")
        assert clear_multiplex_closed_if_soft("open-closed")
        assert not is_multiplex_closed("open-closed")
        transition_stream_resolution(
            "open-closed",
            RowStreamResolutionTrigger.DURABLE_COMPLETE,
        )
        mark_multiplex_closed("open-closed")
        assert not clear_multiplex_closed_if_soft("open-closed")
        assert is_multiplex_closed("open-closed")
    finally:
        reset_stream_resolution_registry_for_tests()


def test_route_terminal_uses_multiplex_closed_not_finished_set() -> None:
    reset_stream_resolution_registry_for_tests()
    try:
        assert route_terminal(RowStreamDelivery.DELIVER, "never-closed") is TerminalRoute.QUEUE
        mark_multiplex_closed("drain-closed")
        assert route_terminal(RowStreamDelivery.DELIVER, "drain-closed") is TerminalRoute.PENDING
        assert route_terminal(RowStreamDelivery.UPGRADE, "never-closed") is TerminalRoute.PENDING
        assert route_terminal(RowStreamDelivery.SILENCE, "drain-closed") is TerminalRoute.SILENCE
    finally:
        reset_stream_resolution_registry_for_tests()
