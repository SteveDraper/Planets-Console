"""Tests for the military score inference CP-SAT solver."""

from api.analytics.military_score_inference.aggregate_action_registry import (
    PLANET_DEFENSE_POST_BUCKETS,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceSolutionAction,
    ProbabilityBucket,
)
from api.analytics.military_score_inference.scoring import (
    LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
    PLANET_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_FIGHTER_SCORE_DELTA_2X,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
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
        probability_weight=100,
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
        probability_weight=50,
    )
    transfer_to_starbase = CandidateAction(
        id="transfer_to_starbase",
        label="Transfer fighters ship to starbase",
        score_delta_2x=-STARBASE_FIGHTER_SCORE_DELTA_2X,
        upper_bound=1,
        probability_weight=10,
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
        probability_weight=100,
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
        probability_weight=100,
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
        probability_weight=100,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
        probability_weight=50,
    )
    paired_build = CandidateAction(
        id="build_small",
        label="Build small hull twice",
        score_delta_2x=200,
        upper_bound=2,
        probability_weight=30,
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=400),
            preferred_build,
            alternate_build,
            paired_build,
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
        probability_weight=100,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
        probability_weight=50,
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
        probability_weight=100,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
        probability_weight=50,
    )
    paired_build = CandidateAction(
        id="build_small",
        label="Build small hull twice",
        score_delta_2x=200,
        upper_bound=2,
        probability_weight=30,
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
        probability_weight=100,
    )
    alternate_build = CandidateAction(
        id="build_alternate",
        label="Build alternate hull",
        score_delta_2x=400,
        upper_bound=1,
        probability_weight=50,
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


def test_bucketed_defense_posts_use_different_marginal_penalties_for_10_and_100():
    action = _planet_defense_posts_action()
    buckets = {"planet_defense_posts": PLANET_DEFENSE_POST_BUCKETS}

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
    assert result_ten.solutions[0].objective_value == 0
    assert result_hundred.solutions[0].objective_value == -95


def test_bucketed_action_satisfies_exact_score_constraint():
    action = _planet_defense_posts_action()
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=55 * PLANET_DEFENSE_POST_SCORE_DELTA_2X),
            action,
            probability_buckets_by_action_id={"planet_defense_posts": PLANET_DEFENSE_POST_BUCKETS},
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
            probability_buckets_by_action_id={"planet_defense_posts": PLANET_DEFENSE_POST_BUCKETS},
        )
    )

    active_bins = result.diagnostics["rankingBinIndicatorsByActionId"]["planet_defense_posts"]
    assert active_bins == (0, 0, 1)


def test_solver_diagnostics_include_build_time_ranking_metadata():
    torp_actions = tuple(
        CandidateAction(
            id=f"ship_torps_loaded_{torp_id}",
            label=f"Torpedoes {torp_id}",
            score_delta_2x=100,
            upper_bound=2,
            probability_weight=10,
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
    assert result.diagnostics["rankingHeuristics"]["parsimonyPerActiveSlackType"] == -50
    assert "diversityCapsApplied" in result.diagnostics
    diversity_caps = result.diagnostics["diversityCapsApplied"]
    assert isinstance(diversity_caps, list)
    assert any(entry["superclass"] == "torpedo_loads" for entry in diversity_caps)
