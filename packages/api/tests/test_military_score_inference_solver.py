"""Tests for the military score inference CP-SAT solver."""

import pytest
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceSolutionAction,
    ProbabilityBucket,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.scoring import (
    LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
    PLANET_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_FIGHTER_SCORE_DELTA_2X,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
)

from tests.fixtures.military_score_inference_prior_weights import (
    probability_buckets_for_test_action,
)

_PLANET_DEFENSE_POST_TEST_BUCKETS = probability_buckets_for_test_action(
    "planet_defense_posts_added_total"
)


def _observation(
    *,
    military_delta_2x: int = 0,
    warship_delta: int = 0,
    freighter_delta: int = 0,
    priority_point_delta: int = 0,
    starbases_owned: int = 3,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=priority_point_delta,
        starbases_owned=starbases_owned,
        is_after_ship_limit=False,
    )


def _problem(
    observation: InferenceObservation,
    *actions: CandidateAction,
    max_solutions: int = 20,
    time_limit_seconds: float = 1.0,
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]] | None = None,
) -> InferenceProblem:
    return InferenceProblem(
        observation=observation,
        aggregate_actions=actions,
        probability_buckets_by_action_id=probability_buckets_by_action_id or {},
        max_solutions=max_solutions,
        time_limit_seconds=time_limit_seconds,
    )


def _planet_defense_posts_action(*, upper_bound: int = 100) -> CandidateAction:
    return CandidateAction(
        id="planet_defense_posts",
        label="Planet defense posts",
        score_delta_2x=PLANET_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=upper_bound,
    )


def test_cp_model_available_via_solver_module():
    from api.analytics.military_score_inference import solver as inference_solver

    assert inference_solver.cp_model.CpModel is not None


def test_solve_exact_positive_action_solution():
    build_warship = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=400,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=1,
    )
    result = solve_inference_problem(
        _problem(_observation(military_delta_2x=400, warship_delta=1), build_warship)
    )

    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions == (
        InferenceSolutionAction(
            action_id="build_rush",
            label="Build Rush",
            count=1,
        ),
    )
    assert result.solutions[0].objective_value == 0


def test_solve_solution_with_negative_action_contribution():
    load_fighters = CandidateAction(
        id="load_fighters",
        label="Load ship fighters",
        score_delta_2x=LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
        upper_bound=1,
    )
    transfer_to_starbase = CandidateAction(
        id="transfer_to_starbase",
        label="Transfer fighters ship to starbase",
        score_delta_2x=-STARBASE_FIGHTER_SCORE_DELTA_2X,
        upper_bound=1,
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=125),
            load_fighters,
            transfer_to_starbase,
        )
    )

    assert result.status == STATUS_EXACT
    counts = {action.action_id: action.count for action in result.solutions[0].actions}
    assert counts["load_fighters"] == 1
    assert counts["transfer_to_starbase"] == 1


def test_solve_enforced_priority_point_constraint_requires_catalog_pp_deltas():
    build_warship = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=400,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=1,
    )
    problem = InferenceProblem(
        observation=_observation(
            military_delta_2x=400,
            warship_delta=1,
            priority_point_delta=54,
        ),
        aggregate_actions=(build_warship,),
        probability_buckets_by_action_id={},
        enforce_priority_point_constraint=True,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert result.solutions == ()


def test_solve_non_zero_priority_points_with_zero_pp_catalog_actions():
    """Regression: PP delta is diagnostic-only until queue semantics model per-build PP."""
    build_warship = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=400,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=1,
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=400, warship_delta=1, priority_point_delta=54),
            build_warship,
        )
    )

    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].action_id == "build_rush"


def test_solve_pp_only_idle_turn_with_empty_catalog_returns_exact_empty_solution():
    """Regression: scoreboard PP-only rows must not fail when PP is not a hard constraint."""
    result = solve_inference_problem(_problem(_observation(priority_point_delta=2)))

    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 1
    assert result.solutions[0].actions == ()
    assert result.diagnostics["solver_status"] == "NO_ACTIONS"


def test_solve_pp_only_idle_turn_still_infeasible_when_pp_constraint_enforced():
    problem = InferenceProblem(
        observation=_observation(priority_point_delta=2),
        aggregate_actions=(),
        probability_buckets_by_action_id={},
        enforce_priority_point_constraint=True,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert result.solutions == ()


def test_solve_infeasible_problem_returns_no_exact_solution():
    build_warship = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=400,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=1,
    )
    result = solve_inference_problem(
        _problem(_observation(military_delta_2x=401, warship_delta=1), build_warship)
    )

    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert result.solutions == ()


def test_solve_horwasp_player_returns_no_exact_solution_without_solving():
    build_warship = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=400,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=1,
    )
    problem = InferenceProblem(
        observation=_observation(military_delta_2x=400, warship_delta=1),
        aggregate_actions=(build_warship,),
        race_id=12,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert result.solutions == ()
    assert result.diagnostics.get("reason") == "horwasp_unsupported"


def test_solve_invalid_problem_with_bad_action_bounds():
    invalid_action = CandidateAction(
        id="planet_defense_posts",
        label="Planet defense posts",
        score_delta_2x=11,
        lower_bound=5,
        upper_bound=2,
    )
    result = solve_inference_problem(_problem(_observation(military_delta_2x=11), invalid_action))

    assert result.status == STATUS_INVALID_PROBLEM
    assert result.solutions == ()
    assert "lower_bound" in str(result.diagnostics["reason"])


def test_top_k_returns_higher_weight_solutions_first():
    preferred_build = CandidateAction(
        id="build_preferred",
        label="Build preferred hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    paired_build = CandidateAction(
        id="build_small",
        label="Build small hull twice",
        score_delta_2x=200,
        upper_bound=2,
    )
    # Ranking preference is now expressed through per-action bin penalties: the none
    # bin is the max weight, so the gap to the active bin sets the occurrence cost.
    buckets = {
        "build_preferred": (
            ProbabilityBucket("none", 0, 0, 100),
            ProbabilityBucket("active", 1, 1, 100),
        ),
        "build_alternate": (
            ProbabilityBucket("none", 0, 0, 100),
            ProbabilityBucket("active", 1, 1, 50),
        ),
        "build_small": (
            ProbabilityBucket("none", 0, 0, 100),
            ProbabilityBucket("active", 1, 2, 30),
        ),
    }
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=400),
            preferred_build,
            alternate_build,
            paired_build,
            probability_buckets_by_action_id=buckets,
            max_solutions=3,
        )
    )

    assert result.status == STATUS_EXACT
    assert [solution.objective_value for solution in result.solutions] == [0, -50, -70]
    assert result.solutions[0].actions[0].action_id == "build_preferred"


def test_top_k_no_good_cuts_prevent_duplicate_action_vectors():
    preferred_build = CandidateAction(
        id="build_preferred",
        label="Build preferred hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=400),
            preferred_build,
            alternate_build,
            max_solutions=5,
        )
    )

    signatures = [
        tuple(sorted((action.action_id, action.count) for action in solution.actions))
        for solution in result.solutions
    ]
    assert len(signatures) == len(set(signatures))


def test_top_k_stops_at_configured_max_solutions():
    preferred_build = CandidateAction(
        id="build_preferred",
        label="Build preferred hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    paired_build = CandidateAction(
        id="build_small",
        label="Build small hull twice",
        score_delta_2x=200,
        upper_bound=2,
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=400),
            preferred_build,
            alternate_build,
            paired_build,
            max_solutions=2,
        )
    )

    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 2
    assert result.diagnostics["stopped_reason"] == "max_solutions"


def test_top_k_surfaces_time_limited_status(monkeypatch):
    from api.analytics.military_score_inference import solver as inference_solver

    preferred_build = CandidateAction(
        id="build_preferred",
        label="Build preferred hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    solve_calls = {"count": 0}
    original_solve = inference_solver.cp_model.CpSolver.solve

    def solve_once_then_time_out(self, model):
        solve_calls["count"] += 1
        if solve_calls["count"] == 1:
            return original_solve(self, model)
        return inference_solver.cp_model.UNKNOWN

    monkeypatch.setattr(
        inference_solver.cp_model.CpSolver,
        "solve",
        solve_once_then_time_out,
    )

    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=400),
            preferred_build,
            alternate_build,
            max_solutions=5,
        )
    )

    assert result.status == STATUS_TIME_LIMITED
    assert len(result.solutions) == 1
    assert result.diagnostics["time_limited"] is True
    assert result.diagnostics["stopped_reason"] == "time_budget"


def test_effort_clip_unknown_with_hits_is_time_limited_when_spent_short_of_limit(
    monkeypatch,
):
    """Effort path: UNKNOWN + hits is time_limited even if det time < clip.

    OR-Tools can stop on ``max_deterministic_time`` while ``deterministic_time()``
    reports a value short of the clip. Wall and effort share one UNKNOWN+hits
    exhaustion predicate; do not require ``spent + 1e-9 >= limit``.
    """
    from api.analytics.military_score_inference import solver as inference_solver
    from api.analytics.military_score_inference.models import EffortSolveClip

    preferred_build = CandidateAction(
        id="build_preferred",
        label="Build preferred hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    effort_limit = 100.0
    solve_calls = {"count": 0}
    original_solve = inference_solver.cp_model.CpSolver.solve

    def solve_once_then_unknown(self, model):
        solve_calls["count"] += 1
        if solve_calls["count"] == 1:
            return original_solve(self, model)
        return inference_solver.cp_model.UNKNOWN

    monkeypatch.setattr(
        inference_solver.cp_model.CpSolver,
        "solve",
        solve_once_then_unknown,
    )

    result = solve_inference_problem(
        InferenceProblem(
            observation=_observation(military_delta_2x=400),
            aggregate_actions=(preferred_build, alternate_build),
            max_solutions=5,
            time_limit_seconds=1.0,
            solve_clip=EffortSolveClip(max_deterministic_time=effort_limit),
        )
    )

    assert float(result.diagnostics["deterministicTime"]) + 1e-9 < effort_limit
    assert result.status == STATUS_TIME_LIMITED
    assert len(result.solutions) == 1
    assert result.diagnostics["time_limited"] is True
    assert result.diagnostics["stopped_reason"] == "time_budget"


def test_hang_fuse_with_prior_hits_skips_on_solution_and_is_not_time_limited(
    monkeypatch,
):
    """Fuse after structural hits: no admission, not exact, not time_limited."""
    from api.analytics.military_score_inference.models import EffortSolveClip
    from api.analytics.military_score_inference.near_best_structural_search import (
        NearBestStructuralSearchOutcome,
    )
    from ortools.sat.python import cp_model

    preferred_build = CandidateAction(
        id="build_preferred",
        label="Build preferred hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    admitted: list[object] = []

    def fake_collect(*_args, **_kwargs):
        # Simulate hits found before the fuse tripped; admission must still skip.
        return NearBestStructuralSearchOutcome(
            structural_hits=[({"build_preferred": 1}, {})],
            last_solver_status=cp_model.OPTIMAL,
            stopped_reason="hang_fuse",
            time_limited=False,
            hang_fuse_hit=True,
            deterministic_time=0.25,
            solve_wall_seconds=3.5,
            tier_max_objective=0,
            near_best_threshold=0,
            seed_no_goods_applied=0,
            seed_no_goods_skipped=0,
            top_solution_bucket_counts={"build_preferred": (1,)},
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.solver.collect_near_best_structural_hits",
        fake_collect,
    )

    result = solve_inference_problem(
        InferenceProblem(
            observation=_observation(military_delta_2x=400),
            aggregate_actions=(preferred_build,),
            max_solutions=5,
            time_limit_seconds=1.0,
            solve_clip=EffortSolveClip(
                max_deterministic_time=100.0,
                hang_fuse_remaining=1.0,
            ),
        ),
        on_solution=admitted.append,
    )

    assert admitted == []
    assert result.solutions == ()
    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert result.diagnostics.get("time_limited") is not True
    assert result.diagnostics["hangFuseHit"] is True
    assert result.diagnostics["stopped_reason"] == "hang_fuse"
    assert float(result.diagnostics["solveWallSeconds"]) == 3.5


def test_hang_fuse_clears_structural_hits_and_reports_solve_only_wall(monkeypatch):
    """Within one search: a hit then fuse wall clears hits; clock is Solve wall."""
    from api.analytics.military_score_inference import near_best_structural_search as nbs
    from api.analytics.military_score_inference.models import EffortSolveClip

    preferred_build = CandidateAction(
        id="build_preferred",
        label="Build preferred hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
    )
    clock = {"t": 100.0}
    solve_calls = {"count": 0}
    original_invoke = nbs.invoke_cp_sat_solve

    def fake_monotonic() -> float:
        return clock["t"]

    def invoke_then_advance(solver, model, callback=None):
        solve_calls["count"] += 1
        if solve_calls["count"] == 1:
            status = original_invoke(solver, model, callback)
            clock["t"] += 0.05
            return status
        clock["t"] += 2.0
        return nbs.cp_model.UNKNOWN

    monkeypatch.setattr(nbs.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(nbs, "invoke_cp_sat_solve", invoke_then_advance)

    problem = InferenceProblem(
        observation=_observation(military_delta_2x=400),
        aggregate_actions=(preferred_build, alternate_build),
        max_solutions=5,
        time_limit_seconds=1.0,
        solve_clip=EffortSolveClip(
            max_deterministic_time=100.0,
            hang_fuse_remaining=1.0,
        ),
    )
    result = solve_inference_problem(problem)

    assert solve_calls["count"] >= 2
    assert result.diagnostics["hangFuseHit"] is True
    assert result.diagnostics.get("time_limited") is not True
    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert result.solutions == ()
    assert float(result.diagnostics["solveWallSeconds"]) == pytest.approx(2.05)
    # Collect wall includes Python between solves; fuse charge must use Solve-only.
    assert float(result.diagnostics["wall_time_seconds"]) >= float(
        result.diagnostics["solveWallSeconds"]
    )


def test_solve_clip_owns_remaining_allowance_and_stop() -> None:
    """Effort and wall clips share one next-solve / after-solve policy."""
    from api.analytics.military_score_inference.models import EffortSolveClip, WallSolveClip
    from ortools.sat.python import cp_model

    effort = EffortSolveClip(max_deterministic_time=10.0, hang_fuse_remaining=2.0)
    advanced = effort.next_solve(effort_spent=4.0, elapsed_seconds=99.0)
    assert advanced.clip == EffortSolveClip(max_deterministic_time=6.0, hang_fuse_remaining=2.0)
    assert effort.next_solve(effort_spent=10.0, elapsed_seconds=0.0).time_limited
    assert effort.next_solve(effort_spent=10.0, elapsed_seconds=0.0).clip is None
    fused = EffortSolveClip(max_deterministic_time=10.0, hang_fuse_remaining=0.0)
    assert fused.next_solve(effort_spent=1.0, elapsed_seconds=0.0).hang_fuse

    short = effort.after_solve(
        solver_status=cp_model.UNKNOWN,
        effort_spent=1.0,
        solve_wall_seconds=0.1,
        elapsed_seconds=0.1,
        has_structural_hits=True,
    )
    assert short.time_limited
    assert not short.hang_fuse
    fuse_hit = effort.after_solve(
        solver_status=cp_model.UNKNOWN,
        effort_spent=1.0,
        solve_wall_seconds=2.0,
        elapsed_seconds=2.0,
        has_structural_hits=True,
    )
    assert fuse_hit.hang_fuse
    assert not fuse_hit.time_limited
    kept = effort.after_solve(
        solver_status=cp_model.FEASIBLE,
        effort_spent=10.0,
        solve_wall_seconds=0.2,
        elapsed_seconds=0.2,
        has_structural_hits=False,
    )
    assert kept.time_limited
    assert not kept.hang_fuse

    wall = WallSolveClip(max_time_in_seconds=5.0)
    assert wall.problem_time_limit_seconds() == 5.0
    assert effort.problem_time_limit_seconds() == 0.0
    assert wall.next_solve(effort_spent=0.0, elapsed_seconds=5.0).time_limited
    wall_hit = wall.after_solve(
        solver_status=cp_model.FEASIBLE,
        effort_spent=0.0,
        solve_wall_seconds=1.0,
        elapsed_seconds=5.0,
        has_structural_hits=True,
    )
    assert wall_hit.time_limited
    unknown_hit = wall.after_solve(
        solver_status=cp_model.UNKNOWN,
        effort_spent=0.0,
        solve_wall_seconds=0.2,
        elapsed_seconds=0.2,
        has_structural_hits=True,
    )
    assert unknown_hit.time_limited


def test_bucketed_defense_posts_use_different_marginal_penalties_for_10_and_100():
    action = _planet_defense_posts_action()
    planet_defense_buckets = probability_buckets_for_test_action("planet_defense_posts_added_total")
    buckets = {"planet_defense_posts": planet_defense_buckets}

    result_ten = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=10 * PLANET_DEFENSE_POST_SCORE_DELTA_2X),
            action,
            probability_buckets_by_action_id=buckets,
        )
    )
    result_hundred = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=100 * PLANET_DEFENSE_POST_SCORE_DELTA_2X),
            action,
            probability_buckets_by_action_id=buckets,
        )
    )

    assert result_ten.solutions[0].actions[0].count == 10
    assert result_hundred.solutions[0].actions[0].count == 100
    assert result_ten.solutions[0].objective_value > result_hundred.solutions[0].objective_value
    # Active bins now sit below the none max-weight bin by the occurrence cost; the
    # spacing between the modest and extreme bins (95) is preserved.
    assert result_ten.solutions[0].objective_value == -50
    assert result_hundred.solutions[0].objective_value == -149


def test_bucketed_action_satisfies_exact_score_constraint():
    action = _planet_defense_posts_action()
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=55 * PLANET_DEFENSE_POST_SCORE_DELTA_2X),
            action,
            probability_buckets_by_action_id={
                "planet_defense_posts": _PLANET_DEFENSE_POST_TEST_BUCKETS,
            },
        )
    )

    assert result.status == STATUS_EXACT
    assert result.solutions[0].actions[0].count == 55


def test_bucket_variables_respect_configured_count_ranges():
    action = _planet_defense_posts_action()
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=100 * PLANET_DEFENSE_POST_SCORE_DELTA_2X),
            action,
            probability_buckets_by_action_id={
                "planet_defense_posts": _PLANET_DEFENSE_POST_TEST_BUCKETS,
            },
        )
    )

    active_bins = result.diagnostics["rankingBinIndicatorsByActionId"]["planet_defense_posts"]
    assert active_bins == (0, 0, 0, 0, 1)


def test_solver_diagnostics_include_build_time_ranking_metadata():
    torp_actions = tuple(
        CandidateAction(
            id=f"ship_torps_loaded_{torp_id}",
            label=f"Torpedoes {torp_id}",
            score_delta_2x=100,
            upper_bound=2,
        )
        for torp_id in (1, 2)
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=100),
            *torp_actions,
        )
    )

    assert "rankingHeuristics" in result.diagnostics
    assert "diversityCapsApplied" in result.diagnostics
    diversity_caps = result.diagnostics["diversityCapsApplied"]
    assert isinstance(diversity_caps, list)
    assert any(entry["superclass"] == "torpedo_loads" for entry in diversity_caps)


def test_freighter_only_zero_military_score_uses_fast_path():
    freighter_combo = ShipBuildCombo(
        combo_id=GENERIC_FREIGHTER_COMBO_ID,
        hull_id=0,
        engine_id=0,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Freighter",),
        score_delta_2x=0,
        freighter_delta=1,
        upper_bound=1,
        probability_weight=100,
    )
    warship_combo = ShipBuildCombo(
        combo_id="combo_warship",
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Warship",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=50,
    )
    problem = InferenceProblem(
        observation=_observation(freighter_delta=1),
        aggregate_actions=(),
        ship_build_combos=(warship_combo, freighter_combo),
        max_solutions=20,
        time_limit_seconds=0.001,
    )

    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    assert result.diagnostics["solver_status"] == "FREIGHTER_ONLY_FAST_PATH"
    assert len(result.solutions) == 1
    assert result.solutions[0].ship_builds[0].combo_id == GENERIC_FREIGHTER_COMBO_ID
    assert result.solutions[0].ship_builds[0].count == 1


def test_configured_sat_search_workers_defaults_to_one(monkeypatch):
    from api.analytics.military_score_inference.near_best_structural_search import (
        configured_sat_search_workers,
    )

    monkeypatch.delenv("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS", raising=False)
    assert configured_sat_search_workers() == 1


def test_configured_sat_search_workers_env_override(monkeypatch):
    from api.analytics.military_score_inference.near_best_structural_search import (
        configured_sat_search_workers,
    )

    monkeypatch.setenv("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS", "4")
    assert configured_sat_search_workers() == 4
    monkeypatch.setenv("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS", "0")
    assert configured_sat_search_workers() == 1


def test_ortools_rejects_both_num_workers_and_num_search_workers():
    """Regression: dual non-zero worker params → MODEL_INVALID (fleet '?' bug).

    Near-best search must set only ``num_workers``, not also the deprecated
    ``num_search_workers`` alias.
    """
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    x = model.new_int_var(0, 10, "x")
    model.maximize(x)

    either = cp_model.CpSolver()
    either.parameters.num_workers = 1
    assert either.solve(model) == cp_model.OPTIMAL

    both = cp_model.CpSolver()
    both.parameters.num_workers = 1
    both.parameters.num_search_workers = 1
    assert both.solve(model) == cp_model.MODEL_INVALID
