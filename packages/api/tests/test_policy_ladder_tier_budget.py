"""Ladder wall budgets start at first dispatch and are shared across continues."""

from __future__ import annotations

import time

from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_budget import (
    _TierStepRun,
    ensure_ladder_clock_started,
    remaining_time,
)
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
    resolve_tier_policies,
    tier_step_allowance_seconds,
)


def _minimal_policy_step(
    step_id: str,
    *,
    min_seconds: float = 0.0,
    max_seconds: float | None = None,
) -> InferenceTierPolicyStep:
    return InferenceTierPolicyStep(
        id=step_id,
        filters=InferenceCatalogFilters(
            hulls=ComponentFilter(all=True),
            engines=ComponentFilter(all=True),
            beams=ComponentFilter(all=True),
            launchers=ComponentFilter(all=True),
        ),
        beam_slot_counts="none",
        launcher_slot_counts="none",
        aggregate_allowlist={},
        alpha=50,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
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


def test_tier_step_allowance_absolute_min_when_spendable_starved() -> None:
    steps = resolve_tier_policies()
    torp_index = next(i for i, step in enumerate(steps) if step.id == "admit_ship_torpedoes")
    step = steps[torp_index]
    allowance, reserved, spendable = tier_step_allowance_seconds(
        steps,
        torp_index,
        global_remaining_seconds=2.0,
    )
    assert spendable == max(0.0, 2.0 - reserved)
    assert spendable < step.min_seconds
    assert allowance == step.min_seconds
    assert allowance <= (step.max_seconds or allowance)


def test_tier_step_allowance_steered_cap_when_spendable_ample() -> None:
    steps = resolve_tier_policies()
    torp_index = next(i for i, step in enumerate(steps) if step.id == "admit_ship_torpedoes")
    step = steps[torp_index]
    allowance, reserved, spendable = tier_step_allowance_seconds(
        steps,
        torp_index,
        global_remaining_seconds=20.0,
    )
    assert spendable == max(0.0, 20.0 - reserved)
    assert spendable >= step.min_seconds
    assert step.max_seconds is not None
    assert allowance == min(spendable, step.max_seconds)


def test_ensure_ladder_clock_defers_until_first_stamp() -> None:
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    assert state.started_at is None
    first = ensure_ladder_clock_started(state, now=100.0)
    assert first == 100.0
    assert state.started_at == 100.0
    second = ensure_ladder_clock_started(state, now=200.0)
    assert second == 100.0


def test_continues_share_one_row_budget_from_first_dispatch() -> None:
    """Soft-global remaining is shared from first dispatch; tier slice is separate."""
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
    # ~5s left on soft-global steering clock -- not a fresh 20s.
    assert 0.0 < run.global_remaining_seconds() < 6.0
    # Funded tier allowance still runs (soft global does not abort mid-slice).
    assert run.remaining_seconds() > 19.0
    assert not run.should_stop()


def test_soft_global_exhaustion_does_not_abort_funded_tier() -> None:
    """Absolute mins may overshoot soft global; only tier allowance stops the slice."""
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    started = ensure_ladder_clock_started(state, now=time.monotonic() - 21.0)
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        tier_allowance_seconds=3.0,
        tier_started_at=time.monotonic(),
    )
    assert run.global_remaining_seconds() <= 0
    assert not run.should_stop()
    assert run.remaining_seconds() > 2.0
    assert not state.ladder_complete


def test_stale_pre_deferred_started_at_does_not_abort_funded_tier() -> None:
    """Early-stamped soft-global clock may be exhausted; funded tier slice still runs."""
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    state.started_at = time.monotonic() - 45.0
    assert remaining_time(state.started_at, 20.0) <= 0
    run = _TierStepRun(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=state.started_at,
        tier_allowance_seconds=3.0,
        tier_started_at=time.monotonic(),
    )
    assert run.global_remaining_seconds() <= 0
    assert not run.should_stop()
    assert run.remaining_seconds() > 2.0


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


def test_later_absolute_min_allowance_survives_soft_global_overshoot() -> None:
    """After an absolute-min overshoot, a later min>0 step still gets its floor."""
    steps = (
        _minimal_policy_step("early", max_seconds=8.0),
        _minimal_policy_step("admit_ship_torpedoes", min_seconds=3.0, max_seconds=8.0),
        _minimal_policy_step("modest_planet_defense", min_seconds=1.0, max_seconds=5.0),
    )
    # Soft-global almost gone; first min step overshoots remainder.
    torp_allowance, _, torp_spendable = tier_step_allowance_seconds(
        steps,
        1,
        global_remaining_seconds=1.5,
    )
    assert torp_spendable < steps[1].min_seconds
    assert torp_allowance == steps[1].min_seconds
    # After that overshoot, soft-global remaining is non-positive; later min still floors.
    later_allowance, _, later_spendable = tier_step_allowance_seconds(
        steps,
        2,
        global_remaining_seconds=-1.5,
    )
    assert later_spendable == 0.0
    assert later_allowance == steps[2].min_seconds


def test_batch_ladder_dispatches_later_absolute_mins_after_soft_global_exhaust(
    sample_turn,
    monkeypatch,
) -> None:
    """Batch outer loop must not hard-complete on soft-global exhaust before later mins."""
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder

    steps = (
        _minimal_policy_step("early", max_seconds=8.0),
        _minimal_policy_step("admit_ship_torpedoes", min_seconds=3.0, max_seconds=8.0),
        _minimal_policy_step("modest_planet_defense", min_seconds=1.0, max_seconds=5.0),
    )
    dispatched: list[tuple[str, float]] = []

    def fake_tier_step(
        state: PolicyLadderState,
        observation,
        turn,
        *,
        time_limit_seconds,
        cancel_token=None,
        on_admitted=None,
    ) -> None:
        del observation, turn, cancel_token, on_admitted
        # First dispatch backdates the shared clock so soft-global is already exhausted
        # on the next outer-loop iteration (the pre-fix batch hard-stop fingerprint).
        if state.started_at is None:
            state.started_at = time.monotonic() - 100.0
        step_index = state.next_step_index
        step = state.policy_steps[step_index]
        global_remaining = remaining_time(state.started_at, time_limit_seconds)
        allowance, _, _ = tier_step_allowance_seconds(
            state.policy_steps,
            step_index,
            global_remaining_seconds=global_remaining,
        )
        dispatched.append((step.id, allowance))
        state.next_step_index = step_index + 1
        if state.next_step_index >= len(state.policy_steps):
            state.ladder_complete = True

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.resolve_tier_policies",
        lambda _path=None: steps,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.run_policy_ladder_tier_step",
        fake_tier_step,
    )

    score = sample_turn.scores[0]
    observation = build_inference_observation(score, sample_turn)
    solve_with_policy_ladder(observation, sample_turn, time_limit_seconds=20.0)

    assert [step_id for step_id, _ in dispatched] == [
        "early",
        "admit_ship_torpedoes",
        "modest_planet_defense",
    ]
    assert dispatched[1][1] == 3.0
    assert dispatched[2][1] == 1.0
