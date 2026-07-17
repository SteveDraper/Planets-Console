"""Unit tests for inference row stream resolution."""

from api.analytics.military_score_inference.row_stream_resolution import (
    RowStreamDelivery,
    RowStreamResolution,
    RowStreamResolutionState,
    RowStreamResolutionTrigger,
)


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
