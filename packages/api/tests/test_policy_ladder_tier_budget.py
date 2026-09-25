"""Ladder wall budgets start at first dispatch and are shared across continues."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

from api.analytics.military_score_inference.models import (
    InferenceResult,
    InferenceSolution,
    InferenceSolutionShipBuild,
    WallSolveClip,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_budget import (
    TierStepRun,
    ensure_ladder_clock_started,
    remaining_effort,
    remaining_time,
    tier_step_allowance,
)
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    _solve_seed_progression,
)
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    InferenceCatalogFilters,
    InferenceTierPolicyStep,
    resolve_tier_policies,
)


def _minimal_policy_step(
    step_id: str,
    *,
    min_effort: float = 0.0,
    max_effort: float | None = None,
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
        min_effort=min_effort,
        max_effort=max_effort,
    )


def test_tier_step_allowance_reserves_later_mins() -> None:
    steps = resolve_tier_policies()
    allowance, reserved, spendable = tier_step_allowance(
        steps,
        0,
        global_remaining_effort=20.0,
    )
    later_mins = sum(step.min_effort for step in steps[1:])
    assert reserved == later_mins
    assert spendable == 20.0 - later_mins
    early_max = steps[0].max_effort
    assert early_max is not None
    assert allowance == min(spendable, early_max)


def test_tier_step_allowance_absolute_min_when_spendable_starved() -> None:
    steps = resolve_tier_policies()
    torp_index = next(i for i, step in enumerate(steps) if step.id == "admit_ship_torpedoes")
    step = steps[torp_index]
    allowance, reserved, spendable = tier_step_allowance(
        steps,
        torp_index,
        global_remaining_effort=2.0,
    )
    assert spendable == max(0.0, 2.0 - reserved)
    assert spendable < step.min_effort
    assert allowance == step.min_effort
    assert allowance <= (step.max_effort or allowance)


def test_tier_step_allowance_steered_cap_when_spendable_ample() -> None:
    steps = resolve_tier_policies()
    torp_index = next(i for i, step in enumerate(steps) if step.id == "admit_ship_torpedoes")
    step = steps[torp_index]
    allowance, reserved, spendable = tier_step_allowance(
        steps,
        torp_index,
        global_remaining_effort=20.0,
    )
    assert spendable == max(0.0, 20.0 - reserved)
    assert spendable >= step.min_effort
    assert step.max_effort is not None
    assert allowance == min(spendable, step.max_effort)


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
    run = TierStepRun.for_wall(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        allowance_seconds=20.0,
        tier_started_at=time.monotonic(),
    )
    # ~5s left on soft-global steering clock -- not a fresh 20s.
    assert 0.0 < run.global_remaining_seconds() < 6.0
    # Funded tier allowance still runs (soft global does not abort mid-slice).
    assert run.remaining_seconds() > 19.0
    assert run.peek_stop() is None


def test_soft_global_exhaustion_does_not_abort_funded_tier() -> None:
    """Absolute mins may overshoot soft global; only tier allowance stops the slice."""
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    started = ensure_ladder_clock_started(state, now=time.monotonic() - 21.0)
    run = TierStepRun.for_wall(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        allowance_seconds=3.0,
        tier_started_at=time.monotonic(),
    )
    assert run.global_remaining_seconds() <= 0
    assert run.peek_stop() is None
    assert run.remaining_seconds() > 2.0
    assert not state.ladder_complete


def test_stale_pre_deferred_started_at_does_not_abort_funded_tier() -> None:
    """Early-stamped soft-global clock may be exhausted; funded tier slice still runs."""
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    state.started_at = time.monotonic() - 45.0
    assert remaining_time(state.started_at, 20.0) <= 0
    run = TierStepRun.for_wall(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=state.started_at,
        allowance_seconds=3.0,
        tier_started_at=time.monotonic(),
    )
    assert run.global_remaining_seconds() <= 0
    assert run.peek_stop() is None
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
    run = TierStepRun.for_wall(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        allowance_seconds=20.0,
        tier_started_at=time.monotonic(),
    )
    assert run.peek_stop() is None
    assert run.remaining_seconds() > 19.0


def test_tier_allowance_stop_does_not_complete_ladder() -> None:
    from api.analytics.military_score_inference.policy_ladder_tier_budget import TierStopKind

    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:2]))
    started = ensure_ladder_clock_started(state)
    run = TierStepRun.for_wall(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        allowance_seconds=0.0,
        tier_started_at=time.monotonic(),
    )
    stop = run.peek_stop()
    assert stop is TierStopKind.TIER_TIME
    assert not state.time_limited
    assert not state.ladder_complete
    run.commit_stop(stop)
    assert run.is_tier_only_stop()
    assert state.time_limited
    assert not state.ladder_complete


def test_peek_stop_cancel_does_not_mutate_until_commit() -> None:
    from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
    from api.analytics.military_score_inference.policy_ladder_tier_budget import TierStopKind

    token = InferenceCancelToken()
    token.cancel()
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    started = ensure_ladder_clock_started(state)
    run = TierStepRun.for_wall(
        state,
        time_limit_seconds=20.0,
        cancel_token=token,
        budget_started_at=started,
        allowance_seconds=20.0,
        tier_started_at=time.monotonic(),
    )
    assert run.peek_stop() is TierStopKind.CANCEL
    assert not state.cancelled
    assert not state.ladder_complete
    run.commit_stop(TierStopKind.CANCEL)
    assert state.cancelled
    assert state.ladder_complete
    assert not run.is_tier_only_stop()


def test_later_absolute_min_allowance_survives_soft_global_overshoot() -> None:
    """After an absolute-min overshoot, a later min>0 step still gets its floor."""
    steps = (
        _minimal_policy_step("early", max_effort=8.0),
        _minimal_policy_step("admit_ship_torpedoes", min_effort=3.0, max_effort=8.0),
        _minimal_policy_step("modest_planet_defense", min_effort=1.0, max_effort=5.0),
    )
    # Soft-global almost gone; first min step overshoots remainder.
    torp_allowance, _, torp_spendable = tier_step_allowance(
        steps,
        1,
        global_remaining_effort=1.5,
    )
    assert torp_spendable < steps[1].min_effort
    assert torp_allowance == steps[1].min_effort
    # After that overshoot, soft-global remaining is non-positive; later min still floors.
    later_allowance, _, later_spendable = tier_step_allowance(
        steps,
        2,
        global_remaining_effort=-1.5,
    )
    assert later_spendable == 0.0
    assert later_allowance == steps[2].min_effort


def test_batch_ladder_dispatches_later_absolute_mins_after_soft_global_exhaust(
    sample_turn,
    monkeypatch,
) -> None:
    """Batch outer loop must not hard-complete on soft-global exhaust before later mins."""
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder

    steps = (
        _minimal_policy_step("early", max_effort=8.0),
        _minimal_policy_step("admit_ship_torpedoes", min_effort=3.0, max_effort=8.0),
        _minimal_policy_step("modest_planet_defense", min_effort=1.0, max_effort=5.0),
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
        allowance, _, _ = tier_step_allowance(
            state.policy_steps,
            step_index,
            global_remaining_effort=global_remaining,
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


class _SeedProgressionBudget:
    """Monotonic remaining wall that shrinks after each grant (probe-style)."""

    def __init__(self, grants: list[float]) -> None:
        self._grants = list(grants)
        self._index = 0
        self.sampled: list[float] = []

    def should_stop(self) -> bool:
        return self._index >= len(self._grants)

    def next_solve_clip(self):
        if self._index >= len(self._grants):
            return None
        remaining = self._grants[self._index]
        self._index += 1
        self.sampled.append(remaining)
        if remaining <= 0:
            return None
        return WallSolveClip(max_time_in_seconds=remaining)


def _empty_catalog_result() -> InferenceResult:
    return InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={})


def test_seed_progression_samples_remaining_per_sub_solve(monkeypatch) -> None:
    """Neighborhood 0/1 then unfixed each see a fresh remaining, not one snapshot."""
    recorded_limits: list[float] = []

    def fake_solve_catalog(*_args, **kwargs):
        clip = kwargs["solve_clip"]
        recorded_limits.append(float(clip.max_time_in_seconds))
        return _empty_catalog_result(), MagicMock()

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )
    budget = _SeedProgressionBudget([5.0, 3.0, 1.0])
    seed = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(InferenceSolutionShipBuild(combo_id="c1", label="c1", count=1),),
    )
    result, problem = _solve_seed_progression(
        MagicMock(),
        MagicMock(),
        seed,
        max_solutions=5,
        next_solve_clip=budget.next_solve_clip,
        should_stop=budget.should_stop,
    )
    assert result is None
    assert problem is None
    assert recorded_limits == [5.0, 3.0, 1.0]
    assert budget.sampled == [5.0, 3.0, 1.0]


def test_seed_progression_stops_when_remaining_exhausted(monkeypatch) -> None:
    """Exhausted tier wall skips later neighborhood / unfixed passes."""
    recorded_limits: list[float] = []

    def fake_solve_catalog(*_args, **kwargs):
        clip = kwargs["solve_clip"]
        recorded_limits.append(float(clip.max_time_in_seconds))
        return _empty_catalog_result(), MagicMock()

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )
    budget = _SeedProgressionBudget([2.0])  # one grant only; later remaining is 0
    seed = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(InferenceSolutionShipBuild(combo_id="c1", label="c1", count=1),),
    )
    result, problem = _solve_seed_progression(
        MagicMock(),
        MagicMock(),
        seed,
        max_solutions=5,
        next_solve_clip=budget.next_solve_clip,
        should_stop=budget.should_stop,
    )
    assert result is None
    assert problem is None
    assert recorded_limits == [2.0]
    assert budget.sampled == [2.0]


def test_seed_progression_skips_all_solves_when_should_stop(monkeypatch) -> None:
    calls = 0

    def fake_solve_catalog(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _empty_catalog_result(), MagicMock()

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )
    seed = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(InferenceSolutionShipBuild(combo_id="c1", label="c1", count=1),),
    )
    result, problem = _solve_seed_progression(
        MagicMock(),
        MagicMock(),
        seed,
        max_solutions=5,
        next_solve_clip=lambda: WallSolveClip(max_time_in_seconds=5.0),
        should_stop=lambda: True,
    )
    assert result is None
    assert problem is None
    assert calls == 0


def test_delay_between_continues_does_not_reduce_remaining_effort() -> None:
    """Queue / exclusive-drain delay is not inference search effort."""
    state = PolicyLadderState(policy_steps=())
    state.search_effort_spent = 4.0
    before = remaining_effort(74.972, state.search_effort_spent)
    time.sleep(0.05)
    assert remaining_effort(74.972, state.search_effort_spent) == before


def test_zero_min_and_zero_remaining_effort_skips() -> None:
    steps = (
        _minimal_policy_step("early", min_effort=0.0, max_effort=8.0),
        _minimal_policy_step("later", min_effort=0.0, max_effort=5.0),
    )
    allowance, _, spendable = tier_step_allowance(
        steps,
        1,
        global_remaining_effort=0.0,
    )
    assert spendable == 0.0
    assert allowance == 0.0


def test_positive_min_runs_when_remaining_effort_is_below_min() -> None:
    steps = (_minimal_policy_step("funded", min_effort=9.891, max_effort=28.153),)
    allowance, _, spendable = tier_step_allowance(
        steps,
        0,
        global_remaining_effort=1.0,
    )
    assert spendable < 9.891
    assert allowance == 9.891


def test_effort_exhaustion_records_time_limited() -> None:
    from api.analytics.military_score_inference.policy_ladder_tier_budget import TierStopKind

    state = PolicyLadderState(policy_steps=())
    run = TierStepRun.for_effort(
        state,
        cancel_token=None,
        allowance=5.0,
        reserved_for_later=0.0,
        spendable=5.0,
        row_effort_allowance=5.0,
        hang_fuse_seconds=900.0,
        budget_started_at=0.0,
    )
    run.charge_search(deterministic_time=5.0, wall_seconds=0.2)
    assert run.peek_stop() is TierStopKind.TIER_TIME
    run.commit_stop(TierStopKind.TIER_TIME)
    assert state.time_limited
    assert not state.ladder_complete


def test_hang_fuse_does_not_mark_time_limited() -> None:
    from api.analytics.military_score_inference.policy_ladder_tier_budget import TierStopKind
    from api.analytics.military_score_inference.search_effort import InferenceSearchHangFuse

    state = PolicyLadderState(policy_steps=())
    run = TierStepRun.for_effort(
        state,
        cancel_token=None,
        allowance=20.0,
        reserved_for_later=0.0,
        spendable=20.0,
        row_effort_allowance=20.0,
        hang_fuse_seconds=1.0,
        budget_started_at=0.0,
    )
    run.charge_search(deterministic_time=0.1, wall_seconds=1.0)
    assert run.peek_stop() is TierStopKind.HANG_FUSE
    try:
        run.commit_stop(TierStopKind.HANG_FUSE)
    except InferenceSearchHangFuse:
        pass
    else:
        raise AssertionError("hang fuse must fail the step closed")
    assert not state.time_limited
    assert not state.ladder_complete


def test_charge_effort_uses_solve_wall_seconds_then_fails_closed() -> None:
    """Row fuse clock is Solve-only wall; hangFuseHit raises after charge."""
    from api.analytics.military_score_inference.policy_ladder_tier_step import (
        _charge_effort_budget,
    )
    from api.analytics.military_score_inference.search_effort import InferenceSearchHangFuse

    state = PolicyLadderState(policy_steps=())
    run = TierStepRun.for_effort(
        state,
        cancel_token=None,
        allowance=20.0,
        reserved_for_later=0.0,
        spendable=20.0,
        row_effort_allowance=20.0,
        hang_fuse_seconds=10.0,
        budget_started_at=0.0,
    )
    result = InferenceResult(
        status=STATUS_NO_EXACT_SOLUTION,
        solutions=(),
        diagnostics={
            "deterministicTime": 0.2,
            "solveWallSeconds": 1.25,
            "wall_time_seconds": 50.0,
            "hangFuseHit": True,
        },
    )
    try:
        _charge_effort_budget(run, result)
    except InferenceSearchHangFuse:
        pass
    else:
        raise AssertionError("hang fuse must fail closed after charge")
    assert state.search_wall_seconds == 1.25
    assert state.search_effort_spent == 0.2
    assert not state.time_limited


def test_wall_stretch_without_deterministic_time_keeps_later_effort() -> None:
    """Solve wall that does not spend deterministic time leaves later harvest funded."""
    steps = (
        _minimal_policy_step("early", min_effort=0.0, max_effort=8.0),
        _minimal_policy_step("later", min_effort=1.0, max_effort=5.0),
    )
    state = PolicyLadderState(policy_steps=steps)
    run = TierStepRun.for_effort(
        state,
        cancel_token=None,
        allowance=8.0,
        reserved_for_later=0.0,
        spendable=8.0,
        row_effort_allowance=20.0,
        hang_fuse_seconds=900.0,
        budget_started_at=0.0,
    )
    run.charge_search(deterministic_time=0.0, wall_seconds=30.0)
    assert run.peek_stop() is None
    later_allowance, _, _ = tier_step_allowance(
        steps,
        1,
        global_remaining_effort=remaining_effort(20.0, state.search_effort_spent),
    )
    assert later_allowance == 5.0


def test_effort_budget_next_solve_clip_is_deterministic_time() -> None:
    from api.analytics.military_score_inference.models import EffortSolveClip

    state = PolicyLadderState(policy_steps=())
    run = TierStepRun.for_effort(
        state,
        cancel_token=None,
        allowance=5.0,
        reserved_for_later=1.0,
        spendable=4.0,
        row_effort_allowance=20.0,
        hang_fuse_seconds=900.0,
    )
    clip = run.next_solve_clip()
    assert isinstance(clip, EffortSolveClip)
    assert clip.max_deterministic_time == 5.0
    assert clip.hang_fuse_remaining == 900.0
    try:
        run.remaining_seconds()
    except TypeError:
        pass
    else:
        raise AssertionError("remaining_seconds must not return effort")


def test_wall_budget_next_solve_clip_is_wall_seconds() -> None:
    state = PolicyLadderState(policy_steps=())
    started = ensure_ladder_clock_started(state)
    run = TierStepRun.for_wall(
        state,
        time_limit_seconds=20.0,
        cancel_token=None,
        budget_started_at=started,
        allowance_seconds=3.0,
        tier_started_at=time.monotonic(),
    )
    clip = run.next_solve_clip(max_slice=0.25)
    assert isinstance(clip, WallSolveClip)
    assert 0.0 < clip.max_time_in_seconds <= 0.25


def test_effort_probe_clip_does_not_feed_wall_seconds() -> None:
    """Degrade probe asks the budget; stream clips are max_deterministic_time."""
    from api.analytics.military_score_inference.models import EffortSolveClip
    from ortools.sat.python import cp_model

    state = PolicyLadderState(policy_steps=())
    run = TierStepRun.for_effort(
        state,
        cancel_token=None,
        allowance=2.0,
        reserved_for_later=0.0,
        spendable=2.0,
        row_effort_allowance=2.0,
        hang_fuse_seconds=100.0,
    )
    clip = run.next_solve_clip(max_slice=0.25)
    assert isinstance(clip, EffortSolveClip)
    assert clip.max_deterministic_time == 0.25
    solver = cp_model.CpSolver()
    clip.apply_to_solver(solver)
    assert solver.parameters.max_deterministic_time == 0.25
    assert solver.parameters.max_time_in_seconds == 100.0


def test_effort_log_appends_one_json_line_when_configured(tmp_path, monkeypatch) -> None:
    from api.analytics.military_score_inference.policy_ladder_tier_finish import (
        _append_effort_log,
    )

    path = tmp_path / "effort-steps.jsonl"
    monkeypatch.setenv("MILITARY_SCORE_INFERENCE_EFFORT_LOG", str(path))
    _append_effort_log({"stepIndex": 6, "searchEffortSpent": 1.25, "durationMs": 40.0})
    line = json.loads(path.read_text(encoding="utf-8"))
    assert line == {"stepIndex": 6, "searchEffortSpent": 1.25, "durationMs": 40.0}
