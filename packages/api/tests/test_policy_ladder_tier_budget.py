"""Ladder wall budgets start at first dispatch and are shared across continues."""

from __future__ import annotations

import time

from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    _TierStepRun,
    ensure_ladder_clock_started,
    remaining_time,
)
from api.analytics.military_score_inference.tier_policy import (
    resolve_tier_policies,
    tier_step_allowance_seconds,
)


def test_tier_step_allowance_reserves_later_mins() -> None:
    steps = resolve_tier_policies()
    allowance, reserved, spendable = tier_step_allowance_seconds(
        steps,
        0,
        global_remaining_seconds=20.0,
    )
    later_mins = sum(step.min_seconds for step in steps[1:])
    assert reserved == later_mins
    assert spendable == 20.0 - later_mins
    early_max = steps[0].max_seconds
    assert early_max is not None
    assert allowance == min(spendable, early_max)


def test_tier_step_allowance_respects_max_without_overshoot() -> None:
    steps = resolve_tier_policies()
    torp_index = next(i for i, step in enumerate(steps) if step.id == "admit_ship_torpedoes")
    allowance, reserved, spendable = tier_step_allowance_seconds(
        steps,
        torp_index,
        global_remaining_seconds=2.0,
    )
    assert spendable == max(0.0, 2.0 - reserved)
    assert allowance == spendable
    assert allowance <= (steps[torp_index].max_seconds or allowance)


def test_ensure_ladder_clock_defers_until_first_stamp() -> None:
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    assert state.started_at is None
    first = ensure_ladder_clock_started(state, now=100.0)
    assert first == 100.0
    assert state.started_at == 100.0
    second = ensure_ladder_clock_started(state, now=200.0)
    assert second == 100.0


def test_continues_share_one_row_budget_from_first_dispatch() -> None:
    """Regression: per-tier fresh 20s windows blew up turn-8 wall/CPU."""
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    started = ensure_ladder_clock_started(state, now=time.monotonic() - 15.0)
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        tier_allowance_seconds=20.0,
        tier_started_at=time.monotonic(),
    )
    # ~5s left on the shared row budget -- not a fresh 20s.
    assert 0.0 < run.remaining_seconds() < 6.0
    assert not run.should_stop()


def test_exhausted_shared_budget_marks_time_limited() -> None:
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    started = ensure_ladder_clock_started(state, now=time.monotonic() - 21.0)
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        tier_allowance_seconds=20.0,
        tier_started_at=time.monotonic(),
    )
    assert run.should_stop()
    assert state.time_limited
    assert state.ladder_complete
    assert run.stop_kind == "global_time"


def test_stale_pre_deferred_started_at_still_exhausts_if_already_stamped() -> None:
    """If a ladder clock was stamped early (legacy path), shared budget still applies."""
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    state.started_at = time.monotonic() - 45.0
    assert remaining_time(state.started_at, 20.0) <= 0
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=state.started_at,
        tier_allowance_seconds=20.0,
        tier_started_at=time.monotonic(),
    )
    assert run.should_stop()


def test_waiting_deps_before_first_dispatch_does_not_burn_shared_budget() -> None:
    """Fury hang fingerprint: RowRun existed early, first tier after a long wait.

    Deferred ``started_at`` means construction/waiting_deps time is not charged.
    """
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    assert state.started_at is None
    # Long wait with no stamp -- budget must still be full at first dispatch.
    time.sleep(0.01)
    started = ensure_ladder_clock_started(state)
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        tier_allowance_seconds=20.0,
        tier_started_at=time.monotonic(),
    )
    assert not run.should_stop()
    assert run.remaining_seconds() > 19.0


def test_tier_allowance_stop_does_not_complete_ladder() -> None:
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:2]))
    started = ensure_ladder_clock_started(state)
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        tier_allowance_seconds=0.0,
        tier_started_at=time.monotonic(),
    )
    assert run.should_stop()
    assert run.is_tier_only_stop()
    assert state.time_limited
    assert not state.ladder_complete
