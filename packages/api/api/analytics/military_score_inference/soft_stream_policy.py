"""Declarative soft-stream delivery policy for scores DAG terminals.

Maps ``(TerminalSource, park_reason | event presence)`` directly to a
:class:`SoftStreamDispatch` for the stream-resolution mixin. One table owns
policy -- no second enum or if-ladder encoding of the same decisions.

Park rows mirror the design park table in ``design-compute-orchestrator.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from api.analytics.scores_park_wake import ScoresParkReason


class TerminalSource(StrEnum):
    """Who is asking to close (or soft-close) the stream row."""

    PARKED = "parked"
    # Durable / failed terminals from ``notify_scope_outcome`` (not park).
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
    park_reason: ScoresParkReason | None
    has_event: bool


# Explicit cells for every (source × park_reason × has_event) the deliverer
# can observe. Park rows follow the design park table; durable/orphan paths
# ignore park_reason (keyed as None).
_SOFT_STREAM_POLICY: dict[_SoftStreamPolicyKey, SoftStreamDispatch] = {
    # PARKED -- design park table
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.MISSING_ROW_RUN, True
    ): SoftStreamDispatch.SILENCE,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.MISSING_ROW_RUN, False
    ): SoftStreamDispatch.SILENCE,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.EMPTY_TIER_OUTCOME, True
    ): SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.EMPTY_TIER_OUTCOME, False
    ): SoftStreamDispatch.ADMIT_REVERT,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.NON_DURABLE_ROW_COMPLETE, True
    ): SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.NON_DURABLE_ROW_COMPLETE, False
    ): SoftStreamDispatch.SILENCE,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, None, True
    ): SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
    _SoftStreamPolicyKey(TerminalSource.PARKED, None, False): SoftStreamDispatch.SILENCE,
    # SCOPE_OUTCOME -- park_reason unused
    _SoftStreamPolicyKey(TerminalSource.SCOPE_OUTCOME, None, True): SoftStreamDispatch.EMIT_DURABLE,
    _SoftStreamPolicyKey(TerminalSource.SCOPE_OUTCOME, None, False): SoftStreamDispatch.ADMIT_FAIL,
    # ORPHAN -- park_reason unused
    _SoftStreamPolicyKey(
        TerminalSource.ORPHAN, None, True
    ): SoftStreamDispatch.EMIT_DURABLE_FINALIZE,
    _SoftStreamPolicyKey(TerminalSource.ORPHAN, None, False): SoftStreamDispatch.ORPHAN_EMPTY,
}


def resolve_soft_stream_dispatch(
    *,
    source: TerminalSource,
    park_reason: ScoresParkReason | str | None,
    has_event: bool,
) -> SoftStreamDispatch:
    """Look up soft-stream dispatch for one park / durable / orphan delivery."""
    reason = _coerce_park_reason(park_reason) if source is TerminalSource.PARKED else None
    key = _SoftStreamPolicyKey(source, reason, has_event)
    return _SOFT_STREAM_POLICY.get(key, SoftStreamDispatch.SILENCE)


def _coerce_park_reason(park_reason: ScoresParkReason | str | None) -> ScoresParkReason | None:
    if park_reason is None:
        return None
    if isinstance(park_reason, ScoresParkReason):
        return park_reason
    try:
        return ScoresParkReason(park_reason)
    except ValueError:
        return None
