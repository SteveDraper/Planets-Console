"""Unit tests for soft-stream policy table lookup."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.soft_stream_policy import (
    SoftStreamDispatch,
    TerminalSource,
    resolve_soft_stream_dispatch,
)
from api.analytics.scores_park_wake import ScoresParkReason


@pytest.mark.parametrize(
    ("source", "park_reason", "has_event", "expected"),
    [
        # Design park table
        (
            TerminalSource.PARKED,
            ScoresParkReason.NON_DURABLE_ROW_COMPLETE,
            True,
            SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.NON_DURABLE_ROW_COMPLETE,
            False,
            SoftStreamDispatch.SILENCE,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.EMPTY_TIER_OUTCOME,
            False,
            SoftStreamDispatch.ADMIT_REVERT,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.EMPTY_TIER_OUTCOME,
            True,
            SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.MISSING_ROW_RUN,
            True,
            SoftStreamDispatch.SILENCE,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.MISSING_ROW_RUN,
            False,
            SoftStreamDispatch.SILENCE,
        ),
        (TerminalSource.PARKED, None, False, SoftStreamDispatch.SILENCE),
        (TerminalSource.PARKED, None, True, SoftStreamDispatch.EMIT_SOFT_PROVISIONAL),
        (TerminalSource.PARKED, "unknown_park", False, SoftStreamDispatch.SILENCE),
        # Durable / orphan (park_reason ignored)
        (
            TerminalSource.SCOPE_OUTCOME,
            ScoresParkReason.EMPTY_TIER_OUTCOME,
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
    park_reason: str | None,
    has_event: bool,
    expected: SoftStreamDispatch,
) -> None:
    assert (
        resolve_soft_stream_dispatch(
            source=source,
            park_reason=park_reason,
            has_event=has_event,
        )
        is expected
    )
