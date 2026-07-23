"""Declarative soft-stream delivery policy for scores DAG terminals.

Maps ``(TerminalSource, soft_terminal_reason | event presence)`` directly to a
:class:`SoftStreamDispatch` for the stream-resolution mixin. One table owns
policy -- no second enum or if-ladder encoding of the same decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from api.analytics.scores_defer_wake import SoftTerminalReason

__all__ = [
    "SoftTerminalReason",
    "SoftStreamDispatch",
    "TerminalSource",
    "resolve_soft_stream_dispatch",
]


class TerminalSource(StrEnum):
    """Who is asking to close (or soft-close) the stream row."""

    # Soft defer from tier/row callbacks while the DAG node stays ``waiting_deps``.
    ROW_DEFER = "row_defer"
    # Durable / failed terminals from ``notify_scope_outcome``.
    SCOPE_OUTCOME = "scope_outcome"
    ORPHAN = "orphan"


class SoftStreamDispatch(StrEnum):
    """How ``_deliver_row_terminal`` executes one soft-stream policy cell.

    Durable emit kinds derive the FSM trigger from the event type
    (``RowComplete`` vs ``RowFailed``); soft provisional always uses
    ``SOFT_PROVISIONAL``.
    """

    SILENCE = "silence"
    EMIT_SOFT_PROVISIONAL = "emit_soft_provisional"
    EMIT_DURABLE = "emit_durable"
    EMIT_DURABLE_FINALIZE = "emit_durable_finalize"
    ADMIT_REVERT = "admit_revert"
    ADMIT_FAIL = "admit_fail"
    ORPHAN_EMPTY = "orphan_empty"


@dataclass(frozen=True, slots=True)
class _SoftStreamPolicyKey:
    source: TerminalSource
    soft_terminal_reason: SoftTerminalReason | None
    has_event: bool


_SOFT_STREAM_POLICY: dict[_SoftStreamPolicyKey, SoftStreamDispatch] = {
    # ROW_DEFER -- former park table, now keyed off row defer reason
    _SoftStreamPolicyKey(
        TerminalSource.ROW_DEFER, SoftTerminalReason.EMPTY_TIER_OUTCOME, True
    ): SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
    _SoftStreamPolicyKey(
        TerminalSource.ROW_DEFER, SoftTerminalReason.EMPTY_TIER_OUTCOME, False
    ): SoftStreamDispatch.ADMIT_REVERT,
    _SoftStreamPolicyKey(
        TerminalSource.ROW_DEFER, SoftTerminalReason.NON_DURABLE_ROW_COMPLETE, True
    ): SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
    _SoftStreamPolicyKey(
        TerminalSource.ROW_DEFER, SoftTerminalReason.NON_DURABLE_ROW_COMPLETE, False
    ): SoftStreamDispatch.SILENCE,
    _SoftStreamPolicyKey(
        TerminalSource.ROW_DEFER, None, True
    ): SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
    _SoftStreamPolicyKey(TerminalSource.ROW_DEFER, None, False): SoftStreamDispatch.SILENCE,
    # SCOPE_OUTCOME -- soft_terminal_reason unused
    _SoftStreamPolicyKey(TerminalSource.SCOPE_OUTCOME, None, True): SoftStreamDispatch.EMIT_DURABLE,
    _SoftStreamPolicyKey(TerminalSource.SCOPE_OUTCOME, None, False): SoftStreamDispatch.ADMIT_FAIL,
    # ORPHAN -- soft_terminal_reason unused
    _SoftStreamPolicyKey(
        TerminalSource.ORPHAN, None, True
    ): SoftStreamDispatch.EMIT_DURABLE_FINALIZE,
    _SoftStreamPolicyKey(TerminalSource.ORPHAN, None, False): SoftStreamDispatch.ORPHAN_EMPTY,
}


def resolve_soft_stream_dispatch(
    *,
    source: TerminalSource,
    soft_terminal_reason: SoftTerminalReason | str | None = None,
    has_event: bool,
) -> SoftStreamDispatch:
    """Look up soft-stream dispatch for one defer / durable / orphan delivery."""
    reason = (
        _coerce_soft_terminal_reason(soft_terminal_reason)
        if source is TerminalSource.ROW_DEFER
        else None
    )
    key = _SoftStreamPolicyKey(source, reason, has_event)
    return _SOFT_STREAM_POLICY.get(key, SoftStreamDispatch.SILENCE)


def _coerce_soft_terminal_reason(
    soft_terminal_reason: SoftTerminalReason | str | None,
) -> SoftTerminalReason | None:
    if soft_terminal_reason is None:
        return None
    if isinstance(soft_terminal_reason, SoftTerminalReason):
        return soft_terminal_reason
    try:
        return SoftTerminalReason(soft_terminal_reason)
    except ValueError:
        return None
