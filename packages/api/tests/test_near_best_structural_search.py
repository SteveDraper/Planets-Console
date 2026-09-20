"""Parent near-best prepares counts, then calls the SAT-session kernel."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ProbabilityBucket,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.near_best_structural_search import (
    add_no_good_cut,
    collect_near_best_structural_hits,
)
from api.compute.sat_session import (
    SatSearchCollectionResult,
    add_assignment_no_good,
    collect_sat_search_assignments,
    int_vars_by_name,
)
from ortools.sat.python import cp_model


def _observation() -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=1,
        military_delta_2x=0,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=0,
        is_after_ship_limit=False,
    )


def _combo(combo_id: str) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=(combo_id,),
        score_delta_2x=0,
        warship_delta=0,
        upper_bound=2,
    )


@dataclass(frozen=True)
class _Catalog:
    combos: tuple[ShipBuildCombo, ...]
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]]


def _distinct_pair_problem() -> tuple[
    InferenceProblem,
    cp_model.CpModel,
    dict[str, cp_model.IntVar],
    dict[str, cp_model.IntVar],
    cp_model.IntVar,
    _Catalog,
]:
    model = cp_model.CpModel()
    action_count_vars = {"x": model.new_int_var(0, 2, "x")}
    combo_count_vars = {"y": model.new_int_var(0, 2, "y")}
    objective = model.new_int_var(0, 4, "obj")
    model.add(action_count_vars["x"] + combo_count_vars["y"] == 2)
    model.add(objective == action_count_vars["x"] + combo_count_vars["y"])
    model.maximize(objective)
    combo = _combo("y")
    catalog = _Catalog(combos=(combo,), members_by_merged_id={"y": (combo,)})
    problem = InferenceProblem(
        observation=_observation(),
        aggregate_actions=(CandidateAction(id="x", label="x", score_delta_2x=0, upper_bound=2),),
        max_solutions=3,
        time_limit_seconds=5.0,
        near_best_objective_threshold=0,
    )
    return problem, model, action_count_vars, combo_count_vars, objective, catalog


def test_collect_near_best_splits_kernel_assignments(monkeypatch: pytest.MonkeyPatch) -> None:
    problem, model, action_count_vars, combo_count_vars, objective, catalog = (
        _distinct_pair_problem()
    )
    buckets = (
        ProbabilityBucket(label="none", lower_count=0, upper_count=0, marginal_weight=1),
        ProbabilityBucket(label="some", lower_count=1, upper_count=2, marginal_weight=1),
    )
    problem = InferenceProblem(
        observation=problem.observation,
        aggregate_actions=problem.aggregate_actions,
        max_solutions=problem.max_solutions,
        time_limit_seconds=problem.time_limit_seconds,
        near_best_objective_threshold=problem.near_best_objective_threshold,
        probability_buckets_by_action_id={"x": buckets},
    )
    canned = SatSearchCollectionResult(
        assignments=[{"x": 2, "y": 0}],
        last_solver_status=cp_model.OPTIMAL,
        last_solver_status_name="OPTIMAL",
        stopped_reason="max_solutions",
        time_limited=False,
        tier_max_objective=2,
    )

    def _fake_collect(*_args: object, **_kwargs: object) -> SatSearchCollectionResult:
        return canned

    monkeypatch.setattr(
        "api.analytics.military_score_inference.near_best_structural_search.collect_sat_search_assignments",
        _fake_collect,
    )
    outcome = collect_near_best_structural_hits(
        problem,
        model=model,
        action_count_vars=action_count_vars,
        combo_count_vars=combo_count_vars,
        objective_var=objective,
        merged_combo_catalog=catalog,
    )
    assert outcome.structural_hits == [({"x": 2}, {"y": 0})]
    assert outcome.stopped_reason == "max_solutions"
    assert outcome.tier_max_objective == 2
    assert outcome.top_solution_bucket_counts["x"] == (0, 1)


def test_collect_near_best_matches_flattened_kernel() -> None:
    problem, model, action_count_vars, combo_count_vars, objective, catalog = (
        _distinct_pair_problem()
    )
    outcome = collect_near_best_structural_hits(
        problem,
        model=model,
        action_count_vars=action_count_vars,
        combo_count_vars=combo_count_vars,
        objective_var=objective,
        merged_combo_catalog=catalog,
    )
    pairs = {(hit[0]["x"], hit[1]["y"]) for hit in outcome.structural_hits}
    assert pairs == {(0, 2), (1, 1), (2, 0)}
    assert outcome.stopped_reason == "max_solutions"


def test_add_no_good_cut_flattens_to_one_map_helper() -> None:
    live = cp_model.CpModel()
    live_action = {"x": live.new_int_var(0, 2, "x")}
    live_combo = {"y": live.new_int_var(0, 2, "y")}
    live.add(live_action["x"] + live_combo["y"] == 2)
    add_no_good_cut(live, live_action, live_combo, {"x": 2}, {"y": 0}, cut_index=1)

    kernel = cp_model.CpModel()
    kernel_vars = {
        "x": kernel.new_int_var(0, 2, "x"),
        "y": kernel.new_int_var(0, 2, "y"),
    }
    kernel.add(kernel_vars["x"] + kernel_vars["y"] == 2)
    add_assignment_no_good(kernel, kernel_vars, {"x": 2, "y": 0}, cut_index=1)

    def _feasible_pairs(model: cp_model.CpModel, names: tuple[str, str]) -> set[tuple[int, int]]:
        named = int_vars_by_name(model)
        collected = collect_sat_search_assignments(
            model,
            count_vars={name: named[name] for name in names},
            names=names,
            max_solutions=4,
            time_limit_seconds=5.0,
            num_workers=1,
        )
        return {(item["x"], item["y"]) for item in collected.assignments}

    live_pairs = _feasible_pairs(live, ("x", "y"))
    kernel_pairs = _feasible_pairs(kernel, ("x", "y"))
    assert live_pairs == kernel_pairs
    assert (2, 0) not in live_pairs


def test_colliding_action_and_combo_names_raise() -> None:
    model = cp_model.CpModel()
    shared = model.new_int_var(0, 1, "shared")
    with pytest.raises(ValueError, match="collide"):
        add_no_good_cut(
            model,
            {"shared": shared},
            {"shared": shared},
            {"shared": 0},
            {"shared": 0},
            cut_index=1,
        )
