"""Unit tests for soft-stream policy table lookup."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.soft_stream_policy import (
    SoftStreamAction,
    SoftStreamDispatch,
    TerminalSource,
    resolve_soft_stream_action,
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
            TerminalSource.SCOPE_OUTCOME,
            ScoresParkReason.EMPTY_TIER_OUTCOME,
            True,
            SoftStreamAction.DURABLE_EVENT,
        ),
        (
            TerminalSource.SCOPE_OUTCOME,
            None,
            False,
            SoftStreamAction.SCOPE_OUTCOME_EMPTY,
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


@pytest.mark.parametrize(
    ("action", "dispatch"),
    [
        (SoftStreamAction.SILENCE, SoftStreamDispatch.SILENCE),
        (SoftStreamAction.SOFT_PROVISIONAL_EVENT, SoftStreamDispatch.EMIT_SOFT_PROVISIONAL),
        (SoftStreamAction.DURABLE_EVENT, SoftStreamDispatch.EMIT_DURABLE),
        (SoftStreamAction.DURABLE_EVENT_FINALIZE, SoftStreamDispatch.EMIT_DURABLE_FINALIZE),
        (SoftStreamAction.CHEAP_ADMIT_REVERT, SoftStreamDispatch.ADMIT_REVERT),
        (SoftStreamAction.SCOPE_OUTCOME_EMPTY, SoftStreamDispatch.ADMIT_FAIL),
        (SoftStreamAction.ORPHAN_EMPTY, SoftStreamDispatch.ORPHAN_EMPTY),
    ],
)
def test_action_to_dispatch_table(action: SoftStreamAction, dispatch: SoftStreamDispatch) -> None:
    """Every SoftStreamAction has exactly one SoftStreamDispatch (no parallel ladder)."""
    from api.analytics.military_score_inference.soft_stream_policy import (
        _SOFT_STREAM_DISPATCH,
    )

    assert _SOFT_STREAM_DISPATCH[action] is dispatch


def test_resolve_soft_stream_dispatch_composes_policy() -> None:
    assert (
        resolve_soft_stream_dispatch(
            source=TerminalSource.PARKED,
            park_reason=ScoresParkReason.EMPTY_TIER_OUTCOME,
            has_event=False,
        )
        is SoftStreamDispatch.ADMIT_REVERT
    )
    assert (
        resolve_soft_stream_dispatch(
            source=TerminalSource.ORPHAN,
            park_reason=None,
            has_event=True,
        )
        is SoftStreamDispatch.EMIT_DURABLE_FINALIZE
    )
