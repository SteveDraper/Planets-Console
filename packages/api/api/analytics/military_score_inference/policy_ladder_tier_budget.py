"""Wall-clock and per-tier allowance guards for one policy-ladder step."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.tier_policy import InferenceTierPolicyStep

__all__ = (
    "TierStepRun",
    "TierStopKind",
    "ensure_ladder_clock_started",
    "remaining_time",
    "tier_step_allowance_seconds",
)


class TierStopKind(StrEnum):
    """Why a tier step must stop polling CP-SAT work."""

    CANCEL = "cancel"
    TIER_TIME = "tier_time"


def remaining_time(started_at: float, time_limit_seconds: float | None) -> float:
    if time_limit_seconds is None:
        return float("inf")
    return time_limit_seconds - (time.monotonic() - started_at)


def ensure_ladder_clock_started(state: PolicyLadderState, *, now: float | None = None) -> float:
    """Stamp ``state.started_at`` on first dispatch; return the monotonic anchor used."""
    if state.started_at is None:
        state.started_at = time.monotonic() if now is None else now
    return state.started_at


def tier_step_allowance_seconds(
    steps: tuple[InferenceTierPolicyStep, ...],
    step_index: int,
    *,
    global_remaining_seconds: float,
) -> tuple[float, float, float]:
    """Return ``(allowance, reserved_for_later, spendable)`` for one ladder step.

    Soft-global remainder **steers** the target slice: later steps' ``min_seconds``
    are reserved so earlier steps prefer not to consume them
    (``spendable = max(0, global_remaining - reserved)``, then capped by
    ``max_seconds``). The current step's ``min_seconds`` is an **absolute floor**
    on allowance even when that exceeds ``spendable`` / soft-global remainder
    (intentional overshoot so high-prior aggregate tiers still run).
    """
    if step_index < 0 or step_index >= len(steps):
        raise ValueError(f"step_index {step_index} out of range for {len(steps)} steps")
    step = steps[step_index]
    reserved = sum(later.min_seconds for later in steps[step_index + 1 :])
    spendable = max(0.0, float(global_remaining_seconds) - reserved)
    steered = spendable
    if step.max_seconds is not None:
        steered = min(steered, step.max_seconds)
    allowance = max(step.min_seconds, steered)
    return allowance, reserved, spendable


@dataclass
class TierStepRun:
    """Cancel and time-budget guards shared across one tier step.

    Soft-global wall budget **steers** each step's target allowance at dispatch
    (via ``tier_step_allowance_seconds``). Once a step has an allowance -- including
    an absolute ``min_seconds`` floor that may overshoot soft-global remainder --
    that tier slice runs until cancelled or the tier allowance is exhausted.
    Soft-global exhaustion alone does not abort an in-flight tier or complete the
    ladder; steps with ``min_seconds == 0`` and zero steered spendable get a zero
    allowance and skip.

    Poll with :meth:`peek_stop` (read-only). Commit ladder/state side effects
    once via :meth:`commit_stop` at a finish site.
    """

    state: PolicyLadderState
    time_limit_seconds: float | None
    cancel_token: InferenceCancelToken | None
    budget_started_at: float
    tier_allowance_seconds: float
    tier_started_at: float
    reserved_for_later_seconds: float = 0.0
    spendable_seconds: float = 0.0
    stop_kind: TierStopKind | None = None

    def global_remaining_seconds(self) -> float:
        return remaining_time(self.budget_started_at, self.time_limit_seconds)

    def tier_remaining_seconds(self) -> float:
        return remaining_time(self.tier_started_at, self.tier_allowance_seconds)

    def peek_stop(self) -> TierStopKind | None:
        """Return why the step should stop, without mutating ladder state."""
        if self.cancel_token is not None and self.cancel_token.is_cancelled():
            return TierStopKind.CANCEL
        if self.tier_remaining_seconds() <= 0:
            return TierStopKind.TIER_TIME
        return None

    def commit_stop(self, kind: TierStopKind) -> None:
        """Apply stop side effects once (cancel completes the ladder; tier time does not)."""
        self.stop_kind = kind
        if kind is TierStopKind.CANCEL:
            self.state.cancelled = True
            self.state.ladder_complete = True
        elif kind is TierStopKind.TIER_TIME:
            self.state.time_limited = True

    def remaining_seconds(self) -> float:
        return self.tier_remaining_seconds()

    def is_tier_only_stop(self) -> bool:
        return self.stop_kind is TierStopKind.TIER_TIME
