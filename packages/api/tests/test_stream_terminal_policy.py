"""Unit tests for the scores stream terminal dispatch."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.stream_terminal_policy import (
    StreamTerminalDispatch,
    TerminalSource,
    resolve_stream_terminal_dispatch,
)


@pytest.mark.parametrize(
    ("source", "has_event", "expected"),
    [
        (TerminalSource.SCOPE_OUTCOME, True, StreamTerminalDispatch.EMIT_DURABLE),
        (TerminalSource.SCOPE_OUTCOME, False, StreamTerminalDispatch.ADMIT_FAIL),
        (TerminalSource.ORPHAN, True, StreamTerminalDispatch.EMIT_DURABLE_FINALIZE),
        (TerminalSource.ORPHAN, False, StreamTerminalDispatch.ORPHAN_EMPTY),
    ],
)
def test_resolve_stream_terminal_dispatch(
    source: TerminalSource,
    has_event: bool,
    expected: StreamTerminalDispatch,
) -> None:
    assert resolve_stream_terminal_dispatch(source=source, has_event=has_event) is expected
