"""Tests for factored ship build combo generation."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.component_eligibility import (
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.scoring import ship_construction_score_delta_2x
from api.analytics.military_score_inference.ship_build_combos import (
    generate_ship_build_combos,
    ship_build_combo_id,
)
from api.analytics.military_score_inference.ship_build_scoring import ship_build_score_delta_2x
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.serialization.turn import turn_info_from_json

from tests.fixtures.military_score_inference import _observation

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "inference_corpus"


def test_combo_id_encodes_component_tuple():
    assert (
        ship_build_combo_id(
            hull_id=13,
            engine_id=9,
            beam_id=3,
            torp_id=6,
            beam_count=8,
            launcher_count=6,
        )
        == "combo_13_9_3_6_8_6"
    )
    assert (
        ship_build_combo_id(
            hull_id=15,
            engine_id=1,
            beam_id=None,
            torp_id=None,
            beam_count=0,
            launcher_count=0,
        )
        == "combo_15_1_none_none_0_0"
    )


def test_minimal_beam_only_and_fully_armed_scores(synthetic_catalog_context):
    hull = synthetic_catalog_context["hulls_by_id"][24]
    engine = synthetic_catalog_context["engines_by_id"][1]
    beam = synthetic_catalog_context["beams_by_id"][1]
    torpedo = synthetic_catalog_context["torpedos_by_id"][1]

    minimal = ship_build_score_delta_2x(hull, engine, None, None, beam_count=0, launcher_count=0)
    beam_only = ship_build_score_delta_2x(
        hull, engine, beam, None, beam_count=hull.beams, launcher_count=0
    )
    armed = ship_build_score_delta_2x(
        hull,
        engine,
        beam,
        torpedo,
        beam_count=hull.beams,
        launcher_count=hull.launchers,
    )

    assert minimal < beam_only < armed or minimal < armed
    assert minimal == ship_construction_score_delta_2x(
        hull.cost + engine.cost * hull.engines,
        hull.tritanium
        + hull.duranium
        + hull.molybdenum
        + (engine.tritanium + engine.duranium + engine.molybdenum) * hull.engines,
    )


def test_freighter_combo_has_zero_military_score(synthetic_catalog_context):
    combos = generate_ship_build_combos(
        _observation(military_delta_2x=0, warship_delta=0, freighter_delta=1),
        **synthetic_catalog_context,
    )
    freighter_combos = [combo for combo in combos if combo.freighter_delta == 1]
    assert freighter_combos
    assert all(combo.score_delta_2x == 0 for combo in freighter_combos)

    warship_combos = generate_ship_build_combos(
        _observation(warship_delta=1),
        **synthetic_catalog_context,
    )
    assert all(combo.score_delta_2x > 0 for combo in warship_combos if combo.warship_delta == 1)


def test_beams_and_launchers_may_be_omitted_independently(synthetic_catalog_context):
    torp_hull = replace(
        synthetic_catalog_context["hulls_by_id"][24],
        launchers=2,
    )
    context = {
        **synthetic_catalog_context,
        "hulls_by_id": {**synthetic_catalog_context["hulls_by_id"], torp_hull.id: torp_hull},
        "buildable_hull_ids": frozenset({torp_hull.id}),
    }
    combos = generate_ship_build_combos(_observation(warship_delta=1), **context)
    beam_launcher_pairs = {
        (combo.beam_count, combo.launcher_count)
        for combo in combos
        if combo.hull_id == torp_hull.id
    }
    assert (torp_hull.beams, 0) in beam_launcher_pairs
    assert (0, torp_hull.launchers) in beam_launcher_pairs
    assert (torp_hull.beams, torp_hull.launchers) in beam_launcher_pairs
    assert (0, 0) in beam_launcher_pairs


def test_multi_engine_hull_scales_engine_cost(synthetic_catalog_context):
    combos = generate_ship_build_combos(
        _observation(warship_delta=1, freighter_delta=1),
        **synthetic_catalog_context,
    )
    carrier_combo = next(combo for combo in combos if combo.hull_id == 71 and combo.beam_count == 0)
    hull = synthetic_catalog_context["hulls_by_id"][71]
    engine = synthetic_catalog_context["engines_by_id"][1]
    engine_minerals = engine.tritanium + engine.duranium + engine.molybdenum
    hull_minerals = hull.tritanium + hull.duranium + hull.molybdenum
    expected = ship_construction_score_delta_2x(
        hull.cost + engine.cost * hull.engines,
        hull_minerals + engine_minerals * hull.engines,
    )
    assert carrier_combo.score_delta_2x == expected
    assert hull.engines == 2


def test_empty_active_lists_jump_to_turn_catalog_for_components():
    settings = json.loads((FIXTURES_ROOT / "628580/info.json").read_text())["settings"]
    with open(FIXTURES_ROOT / "628580/1/turns/3.json") as handle:
        turn = turn_info_from_json(json.load(handle), settings_defaults=settings)
    score = next(s for s in turn.scores if s.ownerid == 1)
    observation = build_inference_observation(score, turn)
    full_step = next(step for step in resolve_tier_policies() if step.id == "full_catalog_exact")
    catalog = build_action_catalog_from_turn(observation, turn, policy_step=full_step)
    combos = catalog.ship_build_combos
    missouri = next(
        (
            combo
            for combo in combos
            if combo.hull_id == 13
            and combo.engine_id == 9
            and combo.beam_id == 3
            and combo.torp_id == 6
            and combo.beam_count == 8
            and combo.launcher_count == 6
        ),
        None,
    )
    assert missouri is not None


def test_early_tier_limits_beam_counts_to_zero_or_max(synthetic_catalog_context):
    hull = synthetic_catalog_context["hulls_by_id"][24]
    context = {
        **synthetic_catalog_context,
        "buildable_hull_ids": frozenset({hull.id}),
        "eligible_torp_ids": frozenset(),
    }
    combos = generate_ship_build_combos(
        _observation(warship_delta=1),
        beam_slot_counts="none",
        launcher_slot_counts="none",
        **context,
    )
    beam_counts = {combo.beam_count for combo in combos if combo.hull_id == hull.id}
    assert beam_counts <= {0, hull.beams}


def test_max_tier_includes_partial_beam_and_launcher_counts(synthetic_catalog_context):
    hull = replace(
        synthetic_catalog_context["hulls_by_id"][24],
        beams=4,
        launchers=3,
    )
    context = {
        **synthetic_catalog_context,
        "hulls_by_id": {**synthetic_catalog_context["hulls_by_id"], hull.id: hull},
        "buildable_hull_ids": frozenset({hull.id}),
    }
    combos = generate_ship_build_combos(
        _observation(warship_delta=1),
        beam_slot_counts="partial",
        launcher_slot_counts="partial",
        **context,
    )
    hull_combos = [combo for combo in combos if combo.hull_id == hull.id]
    beam_counts = {combo.beam_count for combo in hull_combos if combo.launcher_count == 0}
    launcher_counts = {combo.launcher_count for combo in hull_combos if combo.beam_count == 0}
    assert beam_counts == {0, 1, 2, 3, 4}
    assert launcher_counts == {0, 1, 2, 3}


def test_solver_joint_constraints_with_combo_and_aggregate():
    from api.analytics.military_score_inference.models import (
        CandidateAction,
        InferenceProblem,
        ShipBuildCombo,
    )

    load_torps = CandidateAction(
        id="ship_torps_loaded_6",
        label="Loaded torps",
        score_delta_2x=50,
        upper_bound=40,
        probability_weight=10,
    )
    combo = ShipBuildCombo(
        combo_id="combo_13_9_3_6_8_6",
        hull_id=13,
        engine_id=9,
        beam_id=3,
        torp_id=6,
        beam_count=8,
        launcher_count=6,
        labels=("Build Missouri",),
        score_delta_2x=8500,
        warship_delta=1,
        upper_bound=1,
        probability_weight=85,
    )
    problem = InferenceProblem(
        observation=InferenceObservation(
            player_id=1,
            turn=3,
            military_delta_2x=8500 + 40 * 50,
            warship_delta=1,
            freighter_delta=0,
            priority_point_delta=0,
            starbases_owned=1,
            is_after_ship_limit=False,
        ),
        aggregate_actions=(load_torps,),
        ship_build_combos=(combo,),
    )
    result = solve_inference_problem(problem)
    assert result.status == STATUS_EXACT
    assert result.solutions[0].ship_builds[0].combo_id == combo.combo_id
    assert result.solutions[0].actions[0].count == 40


def test_score_equivalent_merge_preserves_distinct_probability_ranked_solutions():
    """Design section 8.6: merged feasibility vars expand to distinct ranked rows."""
    from api.analytics.military_score_inference.models import InferenceProblem, ShipBuildCombo

    combo_high = ShipBuildCombo(
        combo_id="combo_high",
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Build High",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=100,
    )
    combo_low = ShipBuildCombo(
        combo_id="combo_low",
        hull_id=2,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Build Low",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=50,
    )
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=400,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
    )
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(),
        ship_build_combos=(combo_high, combo_low),
        max_solutions=5,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 2
    objective_values = [solution.objective_value for solution in result.solutions]
    assert objective_values == sorted(objective_values, reverse=True)
    assert objective_values == [100, 50]
    combo_ids = {solution.ship_builds[0].combo_id for solution in result.solutions}
    assert combo_ids == {"combo_high", "combo_low"}


def test_solver_no_good_cuts_include_combo_variables():
    from api.analytics.military_score_inference.models import InferenceProblem, ShipBuildCombo

    combo_a = ShipBuildCombo(
        combo_id="combo_a",
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Build A",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=100,
    )
    combo_b = ShipBuildCombo(
        combo_id="combo_b",
        hull_id=2,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Build B",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=50,
    )
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=400,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
    )
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(),
        ship_build_combos=(combo_a, combo_b),
        max_solutions=5,
    )
    result = solve_inference_problem(problem)
    signatures = [
        tuple(
            sorted(
                [(build.combo_id, build.count) for build in solution.ship_builds]
                + [(action.action_id, action.count) for action in solution.actions]
            )
        )
        for solution in result.solutions
    ]
    assert len(signatures) == len(set(signatures))
    assert len(result.solutions) == 2


def test_missouri_host_turn_2_regression_becomes_feasible():
    """Phase 1F missed Transwarp/Plasma/Mk4; the combo catalog includes the true build."""
    settings = json.loads((FIXTURES_ROOT / "628580/info.json").read_text())["settings"]
    with open(FIXTURES_ROOT / "628580/1/turns/3.json") as handle:
        turn = turn_info_from_json(json.load(handle), settings_defaults=settings)
    score = next(s for s in turn.scores if s.ownerid == 1)
    observation = build_inference_observation(score, turn)
    full_step = next(step for step in resolve_tier_policies() if step.id == "full_catalog_exact")
    catalog = build_action_catalog_from_turn(observation, turn, policy_step=full_step)
    missouri_combos = [
        combo
        for combo in catalog.ship_build_combos
        if combo.hull_id == 13
        and combo.engine_id == 9
        and combo.beam_id == 3
        and combo.torp_id == 6
        and combo.beam_count == 8
        and combo.launcher_count == 6
    ]
    assert len(missouri_combos) == 1
    assert missouri_combos[0].score_delta_2x == 8550

    problem = build_inference_problem(observation, catalog, max_solutions=1)
    result = solve_inference_problem(problem)
    assert result.status in (STATUS_EXACT, STATUS_TIME_LIMITED)
    assert result.solutions
    assert any(solution.ship_builds for solution in result.solutions)

    missouri_only = build_inference_problem(
        observation,
        ActionCatalog(
            aggregate_actions=catalog.aggregate_actions,
            ship_build_combos=tuple(missouri_combos),
            probability_buckets_by_action_id=catalog.probability_buckets_by_action_id,
            policy_step_id=catalog.policy_step_id,
            policy_step_index=catalog.policy_step_index,
        ),
    )
    assert solve_inference_problem(missouri_only).status == STATUS_EXACT


def test_early_policy_step_catalog_uses_early_game_band_filters(sample_turn):
    observation = _observation(warship_delta=1, freighter_delta=1, starbases_owned=5)
    early_step = resolve_tier_policies()[0]
    context = turn_catalog_context_for_policy_step(sample_turn, observation.player_id, early_step)
    catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=early_step,
        policy_step_index=0,
    )
    combos = catalog.ship_build_combos
    if not combos:
        pytest.skip("sample turn has no buildable hull combos for observation")
    assert early_step.filters.engines.all
    assert {combo.hull_id for combo in combos} <= context.buildable_hull_ids
    assert {combo.engine_id for combo in combos} <= context.eligible_engine_ids
    combo_beam_ids = {combo.beam_id for combo in combos if combo.beam_id is not None}
    combo_torp_ids = {combo.torp_id for combo in combos if combo.torp_id is not None}
    assert combo_beam_ids <= context.eligible_beam_ids
    assert combo_torp_ids <= context.eligible_torp_ids


def test_missouri_host_turn_2_regression_reports_policy_ladder_diagnostics():
    settings = json.loads((FIXTURES_ROOT / "628580/info.json").read_text())["settings"]
    with open(FIXTURES_ROOT / "628580/1/turns/3.json") as handle:
        turn = turn_info_from_json(json.load(handle), settings_defaults=settings)
    score = next(s for s in turn.scores if s.ownerid == 1)
    payload, _, catalog = run_inference_with_artifacts(score, turn)
    assert payload["status"] in (STATUS_EXACT, STATUS_TIME_LIMITED)
    assert payload["solutionCount"] > 0
    assert payload["diagnostics"]["policy_steps_attempted"]
    policy_steps_attempted = payload["diagnostics"]["policy_steps_attempted"]
    assert payload["diagnostics"]["policy_step_id"] == policy_steps_attempted[-1]
    assert catalog is not None
    assert payload["diagnostics"]["ship_build_combo_count"] > 0
    missouri_combo_id = "combo_13_9_3_6_8_6"
    top_ship_builds = payload["solutions"][0]["shipBuilds"]
    assert any(build["comboId"] == missouri_combo_id for build in top_ship_builds)
    assert "accelerated_segments" in payload["diagnostics"]
