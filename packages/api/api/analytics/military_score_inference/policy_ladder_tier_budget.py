"""Wall-clock and per-tier allowance guards for one policy-ladder step."""

from __future__ import annotations

import time
from dataclasses import dataclass

from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState


def remaining_time(started_at: float, time_limit_seconds: float | None) -> float:
    if time_limit_seconds is None:
        return float("inf")
    return time_limit_seconds - (time.monotonic() - started_at)


def ensure_ladder_clock_started(state: PolicyLadderState, *, now: float | None = None) -> float:
    """Stamp ``state.started_at`` on first dispatch; return the monotonic anchor used."""
    if state.started_at is None:
        state.started_at = time.monotonic() if now is None else now
    return state.started_at


@dataclass
class _TierStepRun:
    """Cancel and time-budget guards shared across one tier step.

    Soft-global wall budget **steers** each step's target allowance at dispatch
    (via ``tier_step_allowance_seconds``). Once a step has an allowance -- including
    an absolute ``min_seconds`` floor that may overshoot soft-global remainder --
    that tier slice runs until cancelled or the tier allowance is exhausted.
    Soft-global exhaustion alone does not abort an in-flight tier or complete the
    ladder; steps with ``min_seconds == 0`` and zero steered spendable get a zero
    allowance and skip.
    """

    state: PolicyLadderState
    time_limit_seconds: float | None
    cancel_token: InferenceCancelToken | None
    budget_started_at: float
    tier_allowance_seconds: float
    tier_started_at: float
    reserved_for_later_seconds: float = 0.0
    spendable_seconds: float = 0.0
    stop_kind: str | None = None  # cancel | tier_time

    def global_remaining_seconds(self) -> float:
        return remaining_time(self.budget_started_at, self.time_limit_seconds)

    def tier_remaining_seconds(self) -> float:
        return remaining_time(self.tier_started_at, self.tier_allowance_seconds)

    def should_stop(self) -> bool:
        if self.cancel_token is not None and self.cancel_token.is_cancelled():
            self.state.cancelled = True
            self.state.ladder_complete = True
            self.stop_kind = "cancel"
            return True
        if self.tier_remaining_seconds() <= 0:
            self.state.time_limited = True
            self.stop_kind = "tier_time"
            return True
        return False

    def remaining_seconds(self) -> float:
        return self.tier_remaining_seconds()

    def is_tier_only_stop(self) -> bool:
        return self.stop_kind == "tier_time"
