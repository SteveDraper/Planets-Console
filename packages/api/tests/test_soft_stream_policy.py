"""Unit tests for soft-stream policy table lookup."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.soft_stream_policy import (
    SoftStreamDispatch,
    SoftTerminalReason,
    TerminalSource,
    resolve_soft_stream_dispatch,
)


@pytest.mark.parametrize(
    ("source", "soft_terminal_reason", "has_event", "expected"),
    [
        # Row defer table (former park table)
        (
            TerminalSource.ROW_DEFER,
            SoftTerminalReason.NON_DURABLE_ROW_COMPLETE,
            True,
            SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
        ),
        (
            TerminalSource.ROW_DEFER,
            SoftTerminalReason.NON_DURABLE_ROW_COMPLETE,
            False,
            SoftStreamDispatch.SILENCE,
        ),
        (
            TerminalSource.ROW_DEFER,
            SoftTerminalReason.EMPTY_TIER_OUTCOME,
            False,
            SoftStreamDispatch.ADMIT_REVERT,
        ),
        (
            TerminalSource.ROW_DEFER,
            SoftTerminalReason.EMPTY_TIER_OUTCOME,
            True,
            SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
        ),
        (
            TerminalSource.ROW_DEFER,
            SoftTerminalReason.MISSING_ROW_RUN,
            True,
            SoftStreamDispatch.SILENCE,
        ),
        (
            TerminalSource.ROW_DEFER,
            SoftTerminalReason.MISSING_ROW_RUN,
            False,
            SoftStreamDispatch.SILENCE,
        ),
        (TerminalSource.ROW_DEFER, None, False, SoftStreamDispatch.SILENCE),
        (TerminalSource.ROW_DEFER, None, True, SoftStreamDispatch.EMIT_SOFT_PROVISIONAL),
        (TerminalSource.ROW_DEFER, "unknown_defer", False, SoftStreamDispatch.SILENCE),
        # Durable / orphan (soft_terminal_reason ignored)
        (
            TerminalSource.SCOPE_OUTCOME,
            SoftTerminalReason.EMPTY_TIER_OUTCOME,
            True,
            SoftStreamDispatch.EMIT_DURABLE,
        ),
        (
            TerminalSource.SCOPE_OUTCOME,
            None,
            False,
            SoftStreamDispatch.ADMIT_FAIL,
        ),
        (
            TerminalSource.ORPHAN,
            None,
            True,
            SoftStreamDispatch.EMIT_DURABLE_FINALIZE,
        ),
        (TerminalSource.ORPHAN, None, False, SoftStreamDispatch.ORPHAN_EMPTY),
    ],
)
def test_resolve_soft_stream_dispatch(
    source: TerminalSource,
    soft_terminal_reason: str | None,
    has_event: bool,
    expected: SoftStreamDispatch,
) -> None:
    assert (
        resolve_soft_stream_dispatch(
            source=source,
            soft_terminal_reason=soft_terminal_reason,
            has_event=has_event,
        )
        is expected
    )
