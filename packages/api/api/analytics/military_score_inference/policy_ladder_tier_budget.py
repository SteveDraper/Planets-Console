"""Per-tier inference search budget: effort clip (stream) or wall clip (batch)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    EffortSolveClip,
    SolveClip,
    WallSolveClip,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.search_effort import InferenceSearchHangFuse
from api.analytics.military_score_inference.tier_policy import InferenceTierPolicyStep

__all__ = (
    "EffortSolveClip",
    "SolveClip",
    "TierStepRun",
    "TierStopKind",
    "WallSolveClip",
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


@dataclass
class _EffortBudget:
    """Stream allowance in inference search effort units."""

    allowance: float
    reserved_for_later: float = 0.0
    spendable: float = 0.0
    row_effort_allowance: float | None = None
    hang_fuse_seconds: float | None = None
    effort_spent_this_step: float = 0.0


@dataclass
class _WallBudget:
    """Batch per-case wall allowance for one tier slice."""

    allowance_seconds: float
    started_at: float
    reserved_for_later: float = 0.0
    spendable: float = 0.0


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
    """Cancel and clip guards shared across one tier step.

    Soft-global remainder **steers** each step's target allowance at dispatch
    (via ``tier_step_allowance``). Once a step has an allowance -- including an
    absolute ``min_effort`` floor that may overshoot soft-global remainder --
    that tier slice runs until cancelled, the tier clip is exhausted, or
    the hang fuse trips. Soft-global exhaustion alone does not abort an
    in-flight tier or complete the ladder; steps with ``min_effort == 0`` and
    zero steered spendable get a zero allowance and skip.

    Stream runs use an effort clip (``max_deterministic_time``); batch runs use
    a wall clip (``max_time_in_seconds``). Callers ask :meth:`next_solve_clip`
    rather than reading a mode flag or smuggling effort through seconds fields.

    Poll with :meth:`peek_stop` (read-only). Commit ladder/state side effects
    once via :meth:`commit_stop` at a finish site. A hang-fuse commit fails
    the step closed and does not mark the row ``time_limited``.
    """

    state: PolicyLadderState
    time_limit_seconds: float | None
    cancel_token: InferenceCancelToken | None
    budget_started_at: float
    _budget: _EffortBudget | _WallBudget = field(repr=False)
    stop_kind: TierStopKind | None = None

    @classmethod
    def for_effort(
        cls,
        state: PolicyLadderState,
        *,
        cancel_token: InferenceCancelToken | None,
        allowance: float,
        reserved_for_later: float,
        spendable: float,
        row_effort_allowance: float | None,
        hang_fuse_seconds: float | None,
        budget_started_at: float = 0.0,
    ) -> TierStepRun:
        return cls(
            state=state,
            time_limit_seconds=None,
            cancel_token=cancel_token,
            budget_started_at=budget_started_at,
            _budget=_EffortBudget(
                allowance=allowance,
                reserved_for_later=reserved_for_later,
                spendable=spendable,
                row_effort_allowance=row_effort_allowance,
                hang_fuse_seconds=hang_fuse_seconds,
            ),
        )

    @classmethod
    def for_wall(
        cls,
        state: PolicyLadderState,
        *,
        time_limit_seconds: float | None,
        cancel_token: InferenceCancelToken | None,
        budget_started_at: float,
        allowance_seconds: float,
        tier_started_at: float,
        reserved_for_later: float = 0.0,
        spendable: float = 0.0,
    ) -> TierStepRun:
        return cls(
            state=state,
            time_limit_seconds=time_limit_seconds,
            cancel_token=cancel_token,
            budget_started_at=budget_started_at,
            _budget=_WallBudget(
                allowance_seconds=allowance_seconds,
                started_at=tier_started_at,
                reserved_for_later=reserved_for_later,
                spendable=spendable,
            ),
        )

    @property
    def is_effort_budget(self) -> bool:
        return isinstance(self._budget, _EffortBudget)

    @property
    def tier_allowance(self) -> float:
        budget = self._budget
        if isinstance(budget, _EffortBudget):
            return budget.allowance
        return budget.allowance_seconds

    @property
    def reserved_for_later(self) -> float:
        return self._budget.reserved_for_later

    @property
    def spendable(self) -> float:
        return self._budget.spendable

    def global_remaining_seconds(self) -> float:
        return remaining_time(self.budget_started_at, self.time_limit_seconds)

    def global_remaining_effort(self) -> float:
        budget = self._budget
        if not isinstance(budget, _EffortBudget):
            return float("inf")
        return remaining_effort(budget.row_effort_allowance, self.state.search_effort_spent)

    def remaining_allowance(self) -> float:
        """Clip remaining in this budget's native units (effort or wall seconds)."""
        budget = self._budget
        if isinstance(budget, _EffortBudget):
            return budget.allowance - budget.effort_spent_this_step
        return remaining_time(budget.started_at, budget.allowance_seconds)

    def remaining_seconds(self) -> float:
        """Wall seconds remaining on a batch clip.

        Effort budgets do not expose effort through this name -- use
        :meth:`remaining_allowance` or :meth:`next_solve_clip`.
        """
        budget = self._budget
        if isinstance(budget, _WallBudget):
            return remaining_time(budget.started_at, budget.allowance_seconds)
        raise TypeError("remaining_seconds is wall-only; use remaining_allowance for effort")

    def hang_fuse_exceeded(self) -> bool:
        budget = self._budget
        if not isinstance(budget, _EffortBudget) or budget.hang_fuse_seconds is None:
            return False
        return self.state.search_wall_seconds >= budget.hang_fuse_seconds

    def hang_fuse_remaining(self) -> float | None:
        budget = self._budget
        if not isinstance(budget, _EffortBudget) or budget.hang_fuse_seconds is None:
            return None
        return budget.hang_fuse_seconds - self.state.search_wall_seconds

    def next_solve_clip(self, *, max_slice: float | None = None) -> SolveClip | None:
        """Fresh Solve clip for one CP-SAT call, or ``None`` when the tier clip is empty."""
        remaining = self.remaining_allowance()
        if remaining <= 0:
            return None
        capped = remaining if max_slice is None else min(max_slice, remaining)
        if capped <= 0:
            return None
        budget = self._budget
        if isinstance(budget, _EffortBudget):
            return EffortSolveClip(
                max_deterministic_time=capped,
                hang_fuse_remaining=self.hang_fuse_remaining(),
            )
        return WallSolveClip(max_time_in_seconds=capped)

    def solve_clip_or_exhausted(self) -> SolveClip:
        """Clip for one Solve, or a zero clip when the tier allowance is already spent."""
        clip = self.next_solve_clip()
        if clip is not None:
            return clip
        if isinstance(self._budget, _EffortBudget):
            return EffortSolveClip(
                max_deterministic_time=0.0,
                hang_fuse_remaining=self.hang_fuse_remaining(),
            )
        return WallSolveClip(max_time_in_seconds=0.0)

    def charge_search(self, *, deterministic_time: float, wall_seconds: float) -> None:
        """Spend effort and search wall. Inter-continue delay is not passed here."""
        budget = self._budget
        if isinstance(budget, _EffortBudget):
            budget.effort_spent_this_step += deterministic_time
            self.state.search_effort_spent += deterministic_time
            self.state.search_wall_seconds += wall_seconds

    def peek_stop(self) -> TierStopKind | None:
        """Return why the step should stop, without mutating ladder state."""
        if self.cancel_token is not None and self.cancel_token.is_cancelled():
            return TierStopKind.CANCEL
        if isinstance(self._budget, _EffortBudget) and self.hang_fuse_exceeded():
            return TierStopKind.HANG_FUSE
        if self.remaining_allowance() <= 0:
            return TierStopKind.TIER_TIME
        return None

    def commit_stop(self, kind: TierStopKind) -> None:
        """Apply stop side effects once.

        Cancel completes the ladder. Tier clip exhaustion marks ``time_limited``
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

    def is_tier_only_stop(self) -> bool:
        return self.stop_kind is TierStopKind.TIER_TIME

    def is_clip_exhausted(self) -> bool:
        """True when the tier clip has no remaining allowance."""
        return self.remaining_allowance() <= 0
