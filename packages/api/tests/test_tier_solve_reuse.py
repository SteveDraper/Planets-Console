"""Pinned seed neighborhoods are skipped, and one tier reuses its merged model."""

from __future__ import annotations

import gc
from dataclasses import replace
from unittest.mock import MagicMock

from api.analytics.military_score_inference import catalog_model
from api.analytics.military_score_inference import near_best_structural_search as near_best
from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.catalog_model import (
    ComboPins,
    build_catalog_merge_plan,
    pinned_member_bounds,
)
from api.analytics.military_score_inference.military_score_window import (
    BandMilitaryScoreWindow,
    ExactMilitaryScoreWindow,
    OvershootMilitaryScoreWindow,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
    WallSolveClip,
)
from api.analytics.military_score_inference.pinned_seed_screen import pinned_counts_cannot_explain
from api.analytics.military_score_inference.policy_ladder_tier_step import _solve_seed_progression
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_solve_cache import TierSolve, TierSolveCache


def _combo(
    combo_id: str,
    *,
    score: int,
    warship: int = 0,
    freighter: int = 0,
    upper: int = 4,
    weight: int = 1,
    hull_id: int = 1,
) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=hull_id,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=(combo_id,),
        score_delta_2x=score,
        warship_delta=warship,
        freighter_delta=freighter,
        upper_bound=upper,
        probability_weight=weight,
    )


def _observation(
    *,
    military_delta_2x: int,
    warship_delta: int = 0,
    freighter_delta: int = 0,
    starbases_owned: int = 2,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=3,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=0,
        starbases_owned=starbases_owned,
        is_after_ship_limit=False,
    )


def _catalog(*combos: ShipBuildCombo, actions: tuple[CandidateAction, ...] = ()) -> ActionCatalog:
    return ActionCatalog(
        aggregate_actions=actions,
        ship_build_combos=combos,
        probability_buckets_by_action_id={},
    )


def _group_bounds(plan, catalog, member_id: str) -> tuple[int, int]:
    group = plan.groups[plan.member_group_index[member_id]]
    prototype_id = group.prototype.combo_id
    match = next(combo for combo in catalog.combos if combo.combo_id == prototype_id)
    return match.lower_bound, match.upper_bound


def test_catalog_for_pins_bounds_follow_the_neighborhood_rule() -> None:
    pinned_ship = _combo("seed-ship", score=400, warship=1, upper=4)
    other = _combo("other", score=100, warship=1, upper=3, hull_id=8)
    plan = build_catalog_merge_plan((pinned_ship, other))
    exact = ComboPins({"seed-ship": 2}, 0)
    near = ComboPins({"seed-ship": 2}, 1)

    assert pinned_member_bounds(pinned_ship, exact) == (2, 2)
    assert pinned_member_bounds(pinned_ship, near) == (1, 3)
    assert pinned_member_bounds(other, exact) == (0, 0)
    assert pinned_member_bounds(pinned_ship, None) == (0, 4)

    exact_catalog = plan.catalog_for_pins(exact)
    assert _group_bounds(plan, exact_catalog, "seed-ship") == (2, 2)
    assert _group_bounds(plan, exact_catalog, "other") == (0, 0)
    near_catalog = plan.catalog_for_pins(near)
    assert _group_bounds(plan, near_catalog, "seed-ship") == (1, 3)
    assert _group_bounds(plan, near_catalog, "other") == (0, 0)
    assert plan.catalog_for_pins(None) is plan.unconstrained
    assert exact_catalog.members_by_merged_id == plan.unconstrained.members_by_merged_id

    light = _combo("light", score=10, warship=1, upper=4, weight=1, hull_id=2)
    heavy = _combo("heavy", score=10, warship=1, upper=6, weight=9, hull_id=3)
    merged_plan = build_catalog_merge_plan((light, heavy))
    # Heavy is the representative and is not pinned, so the merged lower bound
    # stays 0. The upper bound is the pinned member's neighborhood.
    exact_merged = merged_plan.catalog_for_pins(ComboPins({"light": 2}, 0))
    near_merged = merged_plan.catalog_for_pins(ComboPins({"light": 2}, 1))
    assert _group_bounds(merged_plan, exact_merged, "light") == (0, 2)
    assert _group_bounds(merged_plan, near_merged, "light") == (0, 3)


def test_pinned_screen_rejects_a_ship_that_cannot_meet_exact_military() -> None:
    ship = _combo("seed-ship", score=1620, warship=1, upper=4)
    plan = build_catalog_merge_plan((ship,))
    observation = _observation(military_delta_2x=3240, warship_delta=1)
    fixed = {"seed-ship": 1}

    assert pinned_counts_cannot_explain(plan, observation, (), ComboPins(fixed, 0))
    assert pinned_counts_cannot_explain(plan, observation, (), ComboPins(fixed, 1))


def test_pinned_screen_keeps_a_neighborhood_aggregates_can_finish() -> None:
    ship = _combo("seed-ship", score=1620, warship=1, upper=4)
    plan = build_catalog_merge_plan((ship,))
    observation = _observation(military_delta_2x=3240, warship_delta=1)
    filler = CandidateAction(
        id="score_filler",
        label="Score filler",
        score_delta_2x=1620,
        upper_bound=1,
    )

    assert not pinned_counts_cannot_explain(
        plan, observation, (filler,), ComboPins({"seed-ship": 1}, 0)
    )


def test_pinned_screen_keeps_an_exact_score_match() -> None:
    ship = _combo("seed-ship", score=3240, warship=1, upper=4)
    plan = build_catalog_merge_plan((ship,))
    observation = _observation(military_delta_2x=3240, warship_delta=1)

    assert not pinned_counts_cannot_explain(plan, observation, (), ComboPins({"seed-ship": 1}, 0))


def test_seed_progression_skips_neighborhoods_the_screen_rejects(monkeypatch) -> None:
    calls: list[int | None] = []

    def fake_solve_catalog(*_args, **kwargs):
        pins = kwargs.get("pins")
        calls.append(None if pins is None else pins.neighborhood)
        return (
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            MagicMock(),
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )
    ship = _combo("seed-ship", score=1620, warship=1, upper=4)
    catalog = _catalog(ship)
    cache = TierSolveCache(build_catalog_merge_plan(catalog.ship_build_combos))
    sampled: list[float] = []

    def next_solve_clip():
        sampled.append(1.0)
        return WallSolveClip(max_time_in_seconds=1.0)

    seed = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(InferenceSolutionShipBuild(combo_id="seed-ship", label="seed-ship", count=1),),
    )
    result, problem = _solve_seed_progression(
        _observation(military_delta_2x=3240, warship_delta=1),
        catalog,
        seed,
        max_solutions=5,
        next_solve_clip=next_solve_clip,
        tier_solve_cache=cache,
    )

    assert result is None
    assert problem is None
    assert calls == [None]
    assert sampled == [1.0]


def test_seed_progression_still_runs_a_neighborhood_that_can_explain(monkeypatch) -> None:
    calls: list[int | None] = []

    def fake_solve_catalog(*_args, **kwargs):
        pins = kwargs.get("pins")
        calls.append(None if pins is None else pins.neighborhood)
        return (
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(InferenceSolution(objective_value=1, actions=()),),
                diagnostics={},
            ),
            MagicMock(),
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )
    ship = _combo("seed-ship", score=3240, warship=1, upper=4)
    catalog = _catalog(ship)
    cache = TierSolveCache(build_catalog_merge_plan(catalog.ship_build_combos))
    seed = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(InferenceSolutionShipBuild(combo_id="seed-ship", label="seed-ship", count=1),),
    )
    result, _problem = _solve_seed_progression(
        _observation(military_delta_2x=3240, warship_delta=1),
        catalog,
        seed,
        max_solutions=5,
        next_solve_clip=lambda: WallSolveClip(max_time_in_seconds=1.0),
        tier_solve_cache=cache,
    )

    assert result is not None
    assert result.solutions
    assert calls == [0]


def test_cache_matches_direct_solves_and_builds_the_model_once(monkeypatch) -> None:
    light = _combo("light", score=400, warship=1, upper=1, weight=1, hull_id=2)
    heavy = _combo("heavy", score=400, warship=1, upper=1, weight=4, hull_id=3)
    observation = _observation(military_delta_2x=400, warship_delta=1)
    catalog = _catalog(light, heavy)
    problem = build_inference_problem(
        observation,
        catalog,
        max_solutions=5,
        time_limit_seconds=2.0,
    )
    direct = solve_inference_problem(problem)
    held = direct.solutions[0]
    direct_blocked = solve_inference_problem(problem, seed_no_good_solutions=(held,))
    cache = TierSolveCache(build_catalog_merge_plan(catalog.ship_build_combos))
    builds = 0
    real_build = catalog_model.build_model

    def counting_build(*args, **kwargs):
        nonlocal builds
        builds += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(catalog_model, "build_model", counting_build)
    first = solve_inference_problem(problem, tier_solve=TierSolve(cache))
    blocked = solve_inference_problem(
        problem,
        tier_solve=TierSolve(cache),
        seed_no_good_solutions=(held,),
    )
    blocked_again = solve_inference_problem(
        problem,
        tier_solve=TierSolve(cache),
        seed_no_good_solutions=(held,),
    )

    assert first.status == direct.status == STATUS_EXACT
    assert [solution.ship_builds for solution in first.solutions] == [
        solution.ship_builds for solution in direct.solutions
    ]
    assert blocked.status == blocked_again.status == direct_blocked.status
    assert blocked.diagnostics["seedNoGoodCount"] == direct_blocked.diagnostics["seedNoGoodCount"]
    assert builds == 1


def test_pinned_tier_solve_reuses_one_model_per_pin(monkeypatch) -> None:
    ship = _combo("seed-ship", score=400, warship=1, upper=3)
    observation = _observation(military_delta_2x=800, warship_delta=2)
    catalog = _catalog(ship)
    problem = build_inference_problem(
        observation,
        catalog,
        max_solutions=5,
        time_limit_seconds=2.0,
    )
    cache = TierSolveCache(build_catalog_merge_plan(catalog.ship_build_combos))
    builds = 0
    real_build = catalog_model.build_model

    def counting_build(*args, **kwargs):
        nonlocal builds
        builds += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(catalog_model, "build_model", counting_build)
    too_low = TierSolve(cache, ComboPins({"seed-ship": 1}, 0))
    fitted = TierSolve(cache, ComboPins({"seed-ship": 2}, 0))
    blocked = solve_inference_problem(problem, tier_solve=too_low)
    blocked_again = solve_inference_problem(problem, tier_solve=too_low)
    solved = solve_inference_problem(problem, tier_solve=fitted)

    assert blocked.status == blocked_again.status == STATUS_NO_EXACT_SOLUTION
    assert solved.status == STATUS_EXACT
    assert solved.solutions[0].ship_builds[0].count == 2
    assert builds == 2


def _open_ship_problem() -> tuple[InferenceProblem, ActionCatalog]:
    ship = _combo("seed-ship", score=400, warship=1, upper=1)
    catalog = _catalog(ship)
    problem = build_inference_problem(
        _observation(military_delta_2x=400, warship_delta=1),
        catalog,
        max_solutions=1,
        time_limit_seconds=1.0,
    )
    return problem, catalog


def _held_solution() -> InferenceSolution:
    return InferenceSolution(objective_value=1, actions=())


def _cache_with_build_counts(monkeypatch, catalog: ActionCatalog):
    cache = TierSolveCache(build_catalog_merge_plan(catalog.ship_build_combos))
    counts = {"builds": 0, "seeds": 0}
    real_build = catalog_model.build_model
    real_seed = near_best.seed_no_good_cuts_for_held_solutions

    def counting_build(*args, **kwargs):
        counts["builds"] += 1
        return real_build(*args, **kwargs)

    def counting_seed(*args, **kwargs):
        counts["seeds"] += 1
        return real_seed(*args, **kwargs)

    monkeypatch.setattr(catalog_model, "build_model", counting_build)
    monkeypatch.setattr(near_best, "seed_no_good_cuts_for_held_solutions", counting_seed)
    return cache, counts


def test_same_held_solutions_reuse_the_built_model(monkeypatch) -> None:
    problem, catalog = _open_ship_problem()
    cache, counts = _cache_with_build_counts(monkeypatch, catalog)
    held = _held_solution()
    cache.fresh_model(problem, None, (held,))
    cache.fresh_model(problem, None, (held,))
    assert counts == {"builds": 1, "seeds": 1}


def test_different_held_solutions_miss_the_seeded_model(monkeypatch) -> None:
    problem, catalog = _open_ship_problem()
    cache, counts = _cache_with_build_counts(monkeypatch, catalog)
    cache.fresh_model(problem, None, (_held_solution(),))
    cache.fresh_model(problem, None, (_held_solution(),))
    assert counts == {"builds": 1, "seeds": 2}


def test_replaced_solution_misses_the_seeded_model(monkeypatch) -> None:
    problem, catalog = _open_ship_problem()
    cache, counts = _cache_with_build_counts(monkeypatch, catalog)
    held = _held_solution()
    cache.fresh_model(problem, None, (held,))
    replaced = replace(held, objective_value=held.objective_value)
    assert replaced == held
    assert replaced.solution_id != held.solution_id
    cache.fresh_model(problem, None, (replaced,))
    assert counts == {"builds": 1, "seeds": 2}


def test_reallocated_solution_misses_the_seeded_model(monkeypatch) -> None:
    problem, catalog = _open_ship_problem()
    cache, counts = _cache_with_build_counts(monkeypatch, catalog)
    held = _held_solution()
    address = id(held)
    original_id = held.solution_id
    cache.fresh_model(problem, None, (held,))
    del held
    gc.collect()
    reborn = _held_solution()
    for _ in range(1000):
        if id(reborn) == address:
            break
        reborn = _held_solution()
    assert reborn.solution_id != original_id
    cache.fresh_model(problem, None, (reborn,))
    assert counts == {"builds": 1, "seeds": 2}


def test_equal_windows_share_a_built_model_and_different_windows_do_not(monkeypatch) -> None:
    problem, catalog = _open_ship_problem()
    cache, counts = _cache_with_build_counts(monkeypatch, catalog)

    def with_window(window):
        return replace(problem, military_score_window=window)

    cache.fresh_model(with_window(ExactMilitaryScoreWindow()), None, ())
    cache.fresh_model(with_window(ExactMilitaryScoreWindow()), None, ())
    assert counts["builds"] == 1

    cache.fresh_model(with_window(BandMilitaryScoreWindow(alpha=10)), None, ())
    cache.fresh_model(with_window(BandMilitaryScoreWindow(alpha=10)), None, ())
    cache.fresh_model(with_window(BandMilitaryScoreWindow(alpha=40)), None, ())
    assert counts["builds"] == 3

    cache.fresh_model(with_window(OvershootMilitaryScoreWindow(cap_2x=20)), None, ())
    cache.fresh_model(with_window(OvershootMilitaryScoreWindow(cap_2x=20)), None, ())
    cache.fresh_model(with_window(OvershootMilitaryScoreWindow(cap_2x=None)), None, ())
    cache.fresh_model(with_window(OvershootMilitaryScoreWindow()), None, ())
    assert counts["builds"] == 5
