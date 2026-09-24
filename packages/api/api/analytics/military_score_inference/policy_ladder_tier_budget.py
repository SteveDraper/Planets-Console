"""Per-tier inference search effort guards, plus batch wall-clock case limits."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.search_effort import InferenceSearchHangFuse
from api.analytics.military_score_inference.tier_policy import InferenceTierPolicyStep

__all__ = (
    "TierStepRun",
    "TierStopKind",
    "ensure_ladder_clock_started",
    "remaining_effort",
    "remaining_time",
    "tier_step_allowance",
)


class TierStopKind(StrEnum):
    """Why a tier step must stop polling CP-SAT work."""

    CANCEL = "cancel"
    TIER_TIME = "tier_time"
    HANG_FUSE = "hang_fuse"


def remaining_effort(allowance: float | None, spent: float) -> float:
    """Effort still available. ``None`` allowance is unlimited. Queue time is not spent."""
    if allowance is None:
        return float("inf")
    return allowance - spent


def remaining_time(started_at: float, time_limit_seconds: float | None) -> float:
    if time_limit_seconds is None:
        return float("inf")
    return time_limit_seconds - (time.monotonic() - started_at)


def ensure_ladder_clock_started(state: PolicyLadderState, *, now: float | None = None) -> float:
    """Stamp ``state.started_at`` on first dispatch; return the monotonic anchor used."""
    if state.started_at is None:
        state.started_at = time.monotonic() if now is None else now
    return state.started_at


def tier_step_allowance(
    steps: tuple[InferenceTierPolicyStep, ...],
    step_index: int,
    *,
    global_remaining_effort: float,
) -> tuple[float, float, float]:
    """Return ``(allowance, reserved_for_later, spendable)`` for one ladder step.

    Soft-global remainder **steers** the target slice: later steps' ``min_effort``
    are reserved so earlier steps prefer not to consume them
    (``spendable = max(0, global_remaining - reserved)``, then capped by
    ``max_effort``). The current step's ``min_effort`` is an **absolute floor**
    on allowance even when that exceeds ``spendable`` / soft-global remainder
    (intentional overshoot so high-prior aggregate tiers still run).
    """
    if step_index < 0 or step_index >= len(steps):
        raise ValueError(f"step_index {step_index} out of range for {len(steps)} steps")
    step = steps[step_index]
    reserved = sum(later.min_effort for later in steps[step_index + 1 :])
    spendable = max(0.0, float(global_remaining_effort) - reserved)
    steered = spendable
    if step.max_effort is not None:
        steered = min(steered, step.max_effort)
    allowance = max(step.min_effort, steered)
    return allowance, reserved, spendable


@dataclass
class TierStepRun:
    """Cancel and allowance guards shared across one tier step.

    Stream steps (``budget_kind="effort"``) spend inference search effort only.
    Batch steps (``budget_kind="wall"``) still clip on the per-case wall limit.

    Soft-global remainder **steers** each step's target allowance at dispatch
    (via ``tier_step_allowance``). Once a step has an allowance -- including an
    absolute ``min_effort`` floor that may overshoot soft-global remainder --
    that tier slice runs until cancelled, the tier allowance is exhausted, or
    the hang fuse trips. Soft-global exhaustion alone does not abort an
    in-flight tier or complete the ladder; steps with ``min_effort == 0`` and
    zero steered spendable get a zero allowance and skip.

    Poll with :meth:`peek_stop` (read-only). Commit ladder/state side effects
    once via :meth:`commit_stop` at a finish site. A hang-fuse commit fails
    the step closed and does not mark the row ``time_limited``.
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
    budget_kind: str = "wall"
    row_effort_allowance: float | None = None
    hang_fuse_seconds: float | None = None
    effort_spent_this_step: float = 0.0

    def global_remaining_seconds(self) -> float:
        return remaining_time(self.budget_started_at, self.time_limit_seconds)

    def global_remaining_effort(self) -> float:
        allowance = self.row_effort_allowance
        if allowance is None:
            return float("inf")
        return remaining_effort(allowance, self.state.search_effort_spent)

    def tier_remaining_seconds(self) -> float:
        return remaining_time(self.tier_started_at, self.tier_allowance_seconds)

    def tier_remaining_effort(self) -> float:
        return self.tier_allowance_seconds - self.effort_spent_this_step

    def hang_fuse_exceeded(self) -> bool:
        if self.budget_kind != "effort" or self.hang_fuse_seconds is None:
            return False
        return self.state.search_wall_seconds >= self.hang_fuse_seconds

    def charge_search(self, *, deterministic_time: float, wall_seconds: float) -> None:
        """Spend effort and search wall. Inter-continue delay is not passed here."""
        self.effort_spent_this_step += deterministic_time
        self.state.search_effort_spent += deterministic_time
        self.state.search_wall_seconds += wall_seconds

    def peek_stop(self) -> TierStopKind | None:
        """Return why the step should stop, without mutating ladder state."""
        if self.cancel_token is not None and self.cancel_token.is_cancelled():
            return TierStopKind.CANCEL
        if self.budget_kind == "effort":
            if self.hang_fuse_exceeded():
                return TierStopKind.HANG_FUSE
            if self.tier_remaining_effort() <= 0:
                return TierStopKind.TIER_TIME
            return None
        if self.tier_remaining_seconds() <= 0:
            return TierStopKind.TIER_TIME
        return None

    def commit_stop(self, kind: TierStopKind) -> None:
        """Apply stop side effects once.

        Cancel completes the ladder. Tier effort exhaustion marks ``time_limited``
        and does not complete the ladder. A hang fuse fails closed.
        """
        self.stop_kind = kind
        if kind is TierStopKind.CANCEL:
            self.state.cancelled = True
            self.state.ladder_complete = True
        elif kind is TierStopKind.TIER_TIME:
            self.state.time_limited = True
        elif kind is TierStopKind.HANG_FUSE:
            raise InferenceSearchHangFuse(
                "inference search hang fuse exceeded; row will not persist"
            )

    def remaining_seconds(self) -> float:
        if self.budget_kind == "effort":
            return self.tier_remaining_effort()
        return self.tier_remaining_seconds()

    def hang_fuse_remaining(self) -> float | None:
        if self.hang_fuse_seconds is None:
            return None
        return self.hang_fuse_seconds - self.state.search_wall_seconds

    def is_tier_only_stop(self) -> bool:
        return self.stop_kind is TierStopKind.TIER_TIME
