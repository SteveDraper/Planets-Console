"""Pure FSM for resolving one row on a multiplexed table stream.

Analytic-independent: soft provisional is a shared capability that scores uses
and fleet simply never triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RowStreamResolutionState(StrEnum):
    """The terminal-delivery state of one stream row."""

    OPEN = "open"
    SOFT_PROVISIONAL = "soft_provisional"
    HARD_TERMINAL = "hard_terminal"
    CANCELED = "canceled"


class RowStreamResolutionTrigger(StrEnum):
    """An adapter event that can resolve a stream row."""

    SOFT_PROVISIONAL = "soft_provisional"
    DURABLE_COMPLETE = "durable_complete"
    DURABLE_FAILURE = "durable_failure"
    ADMISSION_MISSED = "admission_missed"
    CANCELED = "canceled"


class RowStreamDelivery(StrEnum):
    """How the caller must deliver the event selected by a transition."""

    DELIVER = "deliver"
    UPGRADE = "upgrade"
    SILENCE = "silence"


@dataclass
class RowStreamResolution:
    """Reduce stream terminal events into one explicit per-row lifecycle.

    Soft terminals are provisional: a later durable completion upgrades them through
    the pending wire. Hard terminals and cancellations silence all later events.

    ``multiplex_closed`` is independent of FSM state for non-cancel closes (e.g. a
    hard terminal that closes drain after deliver). Cancel-silent multiplex finish
    must seal ``CANCELED`` *and* close drain so late terminals stay silenced.
    """

    state: RowStreamResolutionState = RowStreamResolutionState.OPEN
    multiplex_closed: bool = False

    def transition(self, trigger: RowStreamResolutionTrigger) -> RowStreamDelivery:
        """Apply one trigger and return whether its event reaches the stream."""
        match self.state, trigger:
            case RowStreamResolutionState.OPEN, RowStreamResolutionTrigger.SOFT_PROVISIONAL:
                self.state = RowStreamResolutionState.SOFT_PROVISIONAL
                return RowStreamDelivery.DELIVER
            case (
                RowStreamResolutionState.SOFT_PROVISIONAL,
                RowStreamResolutionTrigger.DURABLE_COMPLETE,
            ):
                self.state = RowStreamResolutionState.HARD_TERMINAL
                return RowStreamDelivery.UPGRADE
            case (
                RowStreamResolutionState.OPEN,
                RowStreamResolutionTrigger.DURABLE_COMPLETE
                | RowStreamResolutionTrigger.DURABLE_FAILURE
                | RowStreamResolutionTrigger.ADMISSION_MISSED,
            ):
                self.state = RowStreamResolutionState.HARD_TERMINAL
                return RowStreamDelivery.DELIVER
            case (
                RowStreamResolutionState.SOFT_PROVISIONAL,
                RowStreamResolutionTrigger.ADMISSION_MISSED
                | RowStreamResolutionTrigger.DURABLE_FAILURE,
            ):
                self.state = RowStreamResolutionState.HARD_TERMINAL
                return RowStreamDelivery.DELIVER
            case _, RowStreamResolutionTrigger.CANCELED:
                self.state = RowStreamResolutionState.CANCELED
                return RowStreamDelivery.SILENCE
            case (
                RowStreamResolutionState.HARD_TERMINAL | RowStreamResolutionState.CANCELED,
                _,
            ):
                # Already resolved; every later trigger is a silenced no-op.
                return RowStreamDelivery.SILENCE
            case (
                RowStreamResolutionState.SOFT_PROVISIONAL,
                RowStreamResolutionTrigger.SOFT_PROVISIONAL,
            ):
                # Duplicate soft-provisional signal; the first one already delivered.
                return RowStreamDelivery.SILENCE
            case _:
                # Unreachable: every (state, trigger) pair is enumerated above.
                return RowStreamDelivery.SILENCE
