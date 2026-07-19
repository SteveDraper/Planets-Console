"""Declarative soft-stream delivery policy for scores DAG terminals.

Maps ``(TerminalSource, park_reason | event presence)`` to a
:class:`SoftStreamAction`, then to a :class:`SoftStreamDispatch` for the
stream-resolution mixin. One table owns policy; one table owns dispatch -- no
second if-ladder encoding of the same decisions.

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


class SoftStreamAction(StrEnum):
    """What soft-stream delivery does for one terminal notification."""

    SILENCE = "silence"
    SOFT_PROVISIONAL_EVENT = "soft_provisional_event"
    CHEAP_ADMIT_REVERT = "cheap_admit_revert"
    DURABLE_EVENT = "durable_event"
    DURABLE_EVENT_FINALIZE = "durable_event_finalize"
    ORPHAN_EMPTY = "orphan_empty"
    SCOPE_OUTCOME_EMPTY = "scope_outcome_empty"


class SoftStreamDispatch(StrEnum):
    """How ``_deliver_row_terminal`` executes one :class:`SoftStreamAction`.

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
_SOFT_STREAM_POLICY: dict[_SoftStreamPolicyKey, SoftStreamAction] = {
    # PARKED -- design park table
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.MISSING_ROW_RUN, True
    ): SoftStreamAction.SILENCE,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.MISSING_ROW_RUN, False
    ): SoftStreamAction.SILENCE,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.EMPTY_TIER_OUTCOME, True
    ): SoftStreamAction.SOFT_PROVISIONAL_EVENT,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.EMPTY_TIER_OUTCOME, False
    ): SoftStreamAction.CHEAP_ADMIT_REVERT,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.NON_DURABLE_ROW_COMPLETE, True
    ): SoftStreamAction.SOFT_PROVISIONAL_EVENT,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, ScoresParkReason.NON_DURABLE_ROW_COMPLETE, False
    ): SoftStreamAction.SILENCE,
    _SoftStreamPolicyKey(
        TerminalSource.PARKED, None, True
    ): SoftStreamAction.SOFT_PROVISIONAL_EVENT,
    _SoftStreamPolicyKey(TerminalSource.PARKED, None, False): SoftStreamAction.SILENCE,
    # SCOPE_OUTCOME -- park_reason unused
    _SoftStreamPolicyKey(TerminalSource.SCOPE_OUTCOME, None, True): SoftStreamAction.DURABLE_EVENT,
    _SoftStreamPolicyKey(
        TerminalSource.SCOPE_OUTCOME, None, False
    ): SoftStreamAction.SCOPE_OUTCOME_EMPTY,
    # ORPHAN -- park_reason unused
    _SoftStreamPolicyKey(
        TerminalSource.ORPHAN, None, True
    ): SoftStreamAction.DURABLE_EVENT_FINALIZE,
    _SoftStreamPolicyKey(TerminalSource.ORPHAN, None, False): SoftStreamAction.ORPHAN_EMPTY,
}

_SOFT_STREAM_DISPATCH: dict[SoftStreamAction, SoftStreamDispatch] = {
    SoftStreamAction.SILENCE: SoftStreamDispatch.SILENCE,
    SoftStreamAction.SOFT_PROVISIONAL_EVENT: SoftStreamDispatch.EMIT_SOFT_PROVISIONAL,
    SoftStreamAction.DURABLE_EVENT: SoftStreamDispatch.EMIT_DURABLE,
    SoftStreamAction.DURABLE_EVENT_FINALIZE: SoftStreamDispatch.EMIT_DURABLE_FINALIZE,
    SoftStreamAction.CHEAP_ADMIT_REVERT: SoftStreamDispatch.ADMIT_REVERT,
    SoftStreamAction.SCOPE_OUTCOME_EMPTY: SoftStreamDispatch.ADMIT_FAIL,
    SoftStreamAction.ORPHAN_EMPTY: SoftStreamDispatch.ORPHAN_EMPTY,
}


def resolve_soft_stream_action(
    *,
    source: TerminalSource,
    park_reason: ScoresParkReason | str | None,
    has_event: bool,
) -> SoftStreamAction:
    """Look up soft-stream policy for one park / durable / orphan delivery."""
    reason = _coerce_park_reason(park_reason) if source is TerminalSource.PARKED else None
    key = _SoftStreamPolicyKey(source, reason, has_event)
    return _SOFT_STREAM_POLICY.get(key, SoftStreamAction.SILENCE)


def resolve_soft_stream_dispatch(
    *,
    source: TerminalSource,
    park_reason: ScoresParkReason | str | None,
    has_event: bool,
) -> SoftStreamDispatch:
    """Policy action plus how ``_deliver_row_terminal`` should execute it."""
    action = resolve_soft_stream_action(
        source=source,
        park_reason=park_reason,
        has_event=has_event,
    )
    return _SOFT_STREAM_DISPATCH[action]


def _coerce_park_reason(park_reason: ScoresParkReason | str | None) -> ScoresParkReason | None:
    if park_reason is None:
        return None
    if isinstance(park_reason, ScoresParkReason):
        return park_reason
    try:
        return ScoresParkReason(park_reason)
    except ValueError:
        return None
