"""Stream tier budgets are measured from dispatch, not ladder construction."""

from __future__ import annotations

import time

from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    _TierStepRun,
    ensure_ladder_clock_started,
    remaining_time,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies


def test_ensure_ladder_clock_defers_until_first_stamp() -> None:
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    assert state.started_at is None
    first = ensure_ladder_clock_started(state, now=100.0)
    assert first == 100.0
    assert state.started_at == 100.0
    second = ensure_ladder_clock_started(state, now=200.0)
    assert second == 100.0


def test_waiting_deps_delay_does_not_exhaust_stream_tier_budget() -> None:
    """Fury hang fingerprint: RowRun created early, first tier after >20s wait.

    Per-tier budget must start at dispatch so the first CP-SAT call still gets a
    full stream_tier_time_limit window.
    """
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    # Simulate ladder constructed while waiting_deps ~45s before dispatch.
    state.started_at = time.monotonic() - 45.0

    assert remaining_time(state.started_at, 20.0) <= 0

    # Old shared-clock behavior would stop immediately. Tier-local anchor must not.
    tier_anchor = time.monotonic()
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=tier_anchor,
    )
    assert not run.should_stop()
    assert run.remaining_seconds() > 15.0
    assert not state.time_limited


def test_exhausted_tier_local_budget_marks_time_limited() -> None:
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    ensure_ladder_clock_started(state)
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=time.monotonic() - 21.0,
    )
    assert run.should_stop()
    assert state.time_limited
    assert state.ladder_complete
