"""Pinned seed neighborhoods are skipped, and one tier reuses its merged model."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    _apply_combo_count_constraints,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
    WallSolveClip,
)
from api.analytics.military_score_inference.pinned_seed_screen import pinned_counts_cannot_explain
from api.analytics.military_score_inference.policy_ladder_tier_step import _solve_seed_progression
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    build_catalog_merge_plan,
    merge_score_equivalent_combos,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_solve_cache import TierSolveCache


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


def _merged_signature(catalog) -> list[tuple[object, ...]]:
    return [
        (
            combo.combo_id,
            combo.lower_bound,
            combo.upper_bound,
            combo.probability_weight,
            combo.labels,
            tuple(member.combo_id for member in catalog.members_by_merged_id[combo.combo_id]),
        )
        for combo in catalog.combos
    ]


def test_merge_plan_matches_score_equivalent_merge_including_pins() -> None:
    freighter = replace(
        _combo(GENERIC_FREIGHTER_COMBO_ID, score=0, freighter=1, upper=3, weight=5, hull_id=0),
        labels=("Freighter",),
    )
    light = _combo("light", score=10, warship=1, upper=4, weight=1, hull_id=2)
    heavy_label = _combo("heavy", score=10, warship=1, upper=6, weight=9, hull_id=3)
    capital = _combo("capital", score=20, warship=1, upper=2, weight=3, hull_id=4)
    combos = (light, freighter, heavy_label, capital)
    plan = build_catalog_merge_plan(combos)

    assert _merged_signature(plan.unconstrained) == _merged_signature(
        merge_score_equivalent_combos(combos)
    )

    fixed = {"light": 2}
    for neighborhood in (0, 1):
        pinned = _apply_combo_count_constraints(
            combos,
            fixed_combo_counts=fixed,
            neighborhood=neighborhood,
        )
        assert _merged_signature(plan.catalog_for_pins(fixed, neighborhood)) == _merged_signature(
            merge_score_equivalent_combos(pinned)
        )


def test_pinned_screen_rejects_a_ship_that_cannot_meet_exact_military() -> None:
    ship = _combo("seed-ship", score=1620, warship=1, upper=4)
    plan = build_catalog_merge_plan((ship,))
    observation = _observation(military_delta_2x=3240, warship_delta=1)
    fixed = {"seed-ship": 1}

    assert pinned_counts_cannot_explain(plan, observation, (), fixed, 0)
    assert pinned_counts_cannot_explain(plan, observation, (), fixed, 1)


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

    assert not pinned_counts_cannot_explain(plan, observation, (filler,), {"seed-ship": 1}, 0)


def test_pinned_screen_keeps_an_exact_score_match() -> None:
    ship = _combo("seed-ship", score=3240, warship=1, upper=4)
    plan = build_catalog_merge_plan((ship,))
    observation = _observation(military_delta_2x=3240, warship_delta=1)

    assert not pinned_counts_cannot_explain(plan, observation, (), {"seed-ship": 1}, 0)


def test_seed_progression_skips_neighborhoods_the_screen_rejects(monkeypatch) -> None:
    calls: list[int | None] = []

    def fake_solve_catalog(*_args, **kwargs):
        calls.append(kwargs.get("combo_count_neighborhood"))
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
        calls.append(kwargs.get("combo_count_neighborhood"))
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
    real_build = __import__(
        "api.analytics.military_score_inference.solver",
        fromlist=["_build_model"],
    )._build_model

    def counting_build(*args, **kwargs):
        nonlocal builds
        builds += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(
        "api.analytics.military_score_inference.solver._build_model",
        counting_build,
    )
    first = solve_inference_problem(problem, tier_solve_cache=cache)
    blocked = solve_inference_problem(
        problem,
        tier_solve_cache=cache,
        seed_no_good_solutions=(held,),
    )
    blocked_again = solve_inference_problem(
        problem,
        tier_solve_cache=cache,
        seed_no_good_solutions=(held,),
    )

    assert first.status == direct.status == STATUS_EXACT
    assert [solution.ship_builds for solution in first.solutions] == [
        solution.ship_builds for solution in direct.solutions
    ]
    assert blocked.status == blocked_again.status == direct_blocked.status
    assert blocked.diagnostics["seedNoGoodCount"] == direct_blocked.diagnostics["seedNoGoodCount"]
    assert builds == 1


def test_cached_pin_matches_a_problem_with_copied_combo_bounds() -> None:
    ship = _combo("seed-ship", score=400, warship=1, upper=3)
    other = _combo("other", score=100, warship=1, upper=3, hull_id=8)
    observation = _observation(military_delta_2x=400, warship_delta=1)
    catalog = _catalog(ship, other)
    pinned_problem = build_inference_problem(
        observation,
        catalog,
        max_solutions=5,
        time_limit_seconds=2.0,
        fixed_combo_counts={"seed-ship": 1},
        combo_count_neighborhood=0,
    )
    open_problem = build_inference_problem(
        observation,
        catalog,
        max_solutions=5,
        time_limit_seconds=2.0,
    )
    direct = solve_inference_problem(pinned_problem)
    via_cache = solve_inference_problem(
        open_problem,
        tier_solve_cache=TierSolveCache(build_catalog_merge_plan(catalog.ship_build_combos)),
        fixed_combo_counts={"seed-ship": 1},
        combo_count_neighborhood=0,
    )

    assert via_cache.status == direct.status
    assert [solution.ship_builds for solution in via_cache.solutions] == [
        solution.ship_builds for solution in direct.solutions
    ]
