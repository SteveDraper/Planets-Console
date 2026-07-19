"""Unit tests for soft-stream policy table lookup."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.soft_stream_policy import (
    SoftStreamAction,
    TerminalSource,
    resolve_soft_stream_action,
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
            SoftStreamAction.SOFT_PROVISIONAL_EVENT,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.NON_DURABLE_ROW_COMPLETE,
            False,
            SoftStreamAction.SILENCE,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.EMPTY_TIER_OUTCOME,
            False,
            SoftStreamAction.CHEAP_ADMIT_REVERT,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.EMPTY_TIER_OUTCOME,
            True,
            SoftStreamAction.SOFT_PROVISIONAL_EVENT,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.MISSING_ROW_RUN,
            True,
            SoftStreamAction.SILENCE,
        ),
        (
            TerminalSource.PARKED,
            ScoresParkReason.MISSING_ROW_RUN,
            False,
            SoftStreamAction.SILENCE,
        ),
        (TerminalSource.PARKED, None, False, SoftStreamAction.SILENCE),
        (TerminalSource.PARKED, None, True, SoftStreamAction.SOFT_PROVISIONAL_EVENT),
        (TerminalSource.PARKED, "unknown_park", False, SoftStreamAction.SILENCE),
        # Durable / orphan
        (
            TerminalSource.NODE_COMPLETE,
            ScoresParkReason.EMPTY_TIER_OUTCOME,
            True,
            SoftStreamAction.DURABLE_EVENT,
        ),
        (
            TerminalSource.NODE_COMPLETE,
            None,
            False,
            SoftStreamAction.NODE_COMPLETE_EMPTY,
        ),
        (
            TerminalSource.ORPHAN,
            None,
            True,
            SoftStreamAction.DURABLE_EVENT_FINALIZE,
        ),
        (TerminalSource.ORPHAN, None, False, SoftStreamAction.ORPHAN_EMPTY),
    ],
)
def test_resolve_soft_stream_action(
    source: TerminalSource,
    park_reason: str | None,
    has_event: bool,
    expected: SoftStreamAction,
) -> None:
    assert (
        resolve_soft_stream_action(
            source=source,
            park_reason=park_reason,
            has_event=has_event,
        )
        is expected
    )
