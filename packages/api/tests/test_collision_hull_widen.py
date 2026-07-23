"""Tests for conditional collision-hull-widen (#226)."""

from __future__ import annotations

from api.analytics.military_score_inference.collision_hull_widen import (
    emitted_low_hull_ids_from_solutions,
    policy_step_with_included_hull_ids,
    resolve_collision_hull_widen_plan,
)
from api.analytics.military_score_inference.hull_collision_twins_asset import (
    HullCollisionTwinTriple,
    admitted_high_hull_ids_for_observation,
    load_hull_collision_twins_for_category,
    military_change_from_delta_2x,
)
from api.analytics.military_score_inference.models import (
    InferenceSolution,
    InferenceSolutionShipBuild,
)
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    resolve_tier_policies,
)
from api.concepts.game_category import GameCategory

from tests.fixtures.military_score_inference import _observation

COLLISION_HULL_WIDEN_STEP_ID = "collision_hull_widen"


def _collision_hull_widen_step(
    steps: tuple[InferenceTierPolicyStep, ...],
) -> InferenceTierPolicyStep:
    return next(step for step in steps if step.hull_collision_twin_widen)


def test_military_change_from_delta_2x() -> None:
    assert military_change_from_delta_2x(5498) == 2749


def test_admitted_high_hull_ids_filters_by_score_and_emitted_lows() -> None:
    asset, _ = load_hull_collision_twins_for_category(GameCategory.EPIC)
    admitted_2749 = admitted_high_hull_ids_for_observation(
        asset,
        emitted_low_hull_ids=frozenset({30}),
        military_change=2749,
        buildable_hull_ids=frozenset({29, 30, 31, 106}),
    )
    assert admitted_2749 == frozenset({31})
    admitted_3281 = admitted_high_hull_ids_for_observation(
        asset,
        emitted_low_hull_ids=frozenset({30}),
        military_change=3281,
        buildable_hull_ids=frozenset({29, 30, 31, 106}),
    )
    assert 29 in admitted_3281
    assert 31 not in admitted_3281


def test_emitted_low_hull_ids_from_solutions_reads_ship_builds() -> None:
    solutions = [
        InferenceSolution(
            objective_value=-171,
            actions=(),
            ship_builds=(
                InferenceSolutionShipBuild(
                    combo_id="valiant",
                    label="Valiant",
                    count=1,
                    hull_id=30,
                ),
            ),
        )
    ]
    assert emitted_low_hull_ids_from_solutions(solutions, catalog=None) == frozenset({30})


def test_resolve_collision_plan_admits_resolute_for_birds_2749(sample_turn, monkeypatch) -> None:
    steps = resolve_tier_policies()
    collision_step = _collision_hull_widen_step(steps)
    asset, path = load_hull_collision_twins_for_category(GameCategory.EPIC)
    assert HullCollisionTwinTriple(30, 31, 2749) in asset.triples

    monkeypatch.setattr(
        "api.analytics.military_score_inference.collision_hull_widen.buildable_hull_ids_for_player",
        lambda *args, **kwargs: frozenset({29, 30, 31, 106}),
    )

    observation = _observation(military_delta_2x=5498, warship_delta=1)
    merged = [
        InferenceSolution(
            objective_value=-171,
            actions=(),
            ship_builds=(
                InferenceSolutionShipBuild(
                    combo_id="valiant",
                    label="Valiant",
                    count=1,
                    hull_id=30,
                ),
            ),
        )
    ]
    plan = resolve_collision_hull_widen_plan(
        collision_step,
        observation=observation,
        turn=sample_turn,
        merged_solutions=merged,
        prior_catalog=None,
        resolved_mask=None,
        twins_asset=asset,
        twins_asset_path=path,
        twins_fell_back=False,
    )
    assert plan.skipped is False
    assert plan.admitted_high_hull_ids == (31,)
    assert plan.emitted_low_hull_ids == (30,)
    assert plan.military_change == 2749
    assert plan.policy_step.filters.hulls.include_component_ids == (31,)
    assert 29 not in plan.admitted_high_hull_ids


def test_resolve_collision_plan_skips_when_no_partners(sample_turn) -> None:
    steps = resolve_tier_policies()
    collision_step = _collision_hull_widen_step(steps)
    asset, path = load_hull_collision_twins_for_category(GameCategory.EPIC)
    observation = _observation(military_delta_2x=2, warship_delta=1)
    plan = resolve_collision_hull_widen_plan(
        collision_step,
        observation=observation,
        turn=sample_turn,
        merged_solutions=[
            InferenceSolution(
                objective_value=-100,
                actions=(),
                ship_builds=(
                    InferenceSolutionShipBuild(
                        combo_id="x",
                        label="x",
                        count=1,
                        hull_id=99999,
                    ),
                ),
            )
        ],
        prior_catalog=None,
        resolved_mask=None,
        twins_asset=asset,
        twins_asset_path=path,
        twins_fell_back=False,
    )
    assert plan.skipped is True
    assert plan.admitted_high_hull_ids == ()
    assert plan.to_diagnostics()["collisionHullWiden"]["skipped"] is True


def test_policy_step_with_included_hull_ids_preserves_step_id() -> None:
    steps = resolve_tier_policies()
    collision_step = _collision_hull_widen_step(steps)
    widened = policy_step_with_included_hull_ids(collision_step, frozenset({31, 29}))
    assert widened.id == COLLISION_HULL_WIDEN_STEP_ID
    assert widened.hull_collision_twin_widen is True
    assert widened.filters.hulls.include_component_ids == (29, 31)
    assert widened.allow_ship_only_exact_early_stop is False
