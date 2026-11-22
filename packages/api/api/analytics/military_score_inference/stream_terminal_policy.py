"""How a scores DAG terminal reaches its table-stream row.

Maps ``(TerminalSource, event presence)`` to a :class:`StreamTerminalDispatch`
for the stream-resolution mixin. This is the one encoding of that decision.
"""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never

__all__ = [
    "StreamTerminalDispatch",
    "TerminalSource",
    "resolve_stream_terminal_dispatch",
]


class TerminalSource(StrEnum):
    """Who is asking to close the stream row."""

    # Durable or failed terminals from ``notify_scope_outcome``.
    SCOPE_OUTCOME = "scope_outcome"
    ORPHAN = "orphan"


class StreamTerminalDispatch(StrEnum):
    """How ``_deliver_row_terminal`` closes one stream row.

    The emit kinds derive the FSM trigger from the event type (``RowComplete``
    vs ``RowFailed``).
    """

    EMIT_DURABLE = "emit_durable"
    EMIT_DURABLE_FINALIZE = "emit_durable_finalize"
    ADMIT_FAIL = "admit_fail"
    ORPHAN_EMPTY = "orphan_empty"


def resolve_stream_terminal_dispatch(
    *,
    source: TerminalSource,
    has_event: bool,
) -> StreamTerminalDispatch:
    """Choose how one durable or orphan terminal closes its stream row."""
    match source:
        case TerminalSource.SCOPE_OUTCOME:
            return (
                StreamTerminalDispatch.EMIT_DURABLE
                if has_event
                else StreamTerminalDispatch.ADMIT_FAIL
            )
        case TerminalSource.ORPHAN:
            return (
                StreamTerminalDispatch.EMIT_DURABLE_FINALIZE
                if has_event
                else StreamTerminalDispatch.ORPHAN_EMPTY
            )
    assert_never(source)
