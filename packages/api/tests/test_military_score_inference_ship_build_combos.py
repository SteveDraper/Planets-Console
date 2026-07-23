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
    GENERIC_FREIGHTER_COMBO_ID,
    GENERIC_ZERO_MILITARY_SCORE_LABEL,
    generate_ship_build_combos,
    is_generic_zero_military_score_combo_id,
    ship_build_combo_id,
)
from api.analytics.military_score_inference.ship_build_scoring import (
    ship_build_counts_as_warship,
    ship_build_military_score_delta_2x,
    ship_build_score_delta_2x,
)
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
    assert len(freighter_combos) == 1
    assert freighter_combos[0].combo_id == GENERIC_FREIGHTER_COMBO_ID
    assert freighter_combos[0].score_delta_2x == 0
    assert freighter_combos[0].labels == (GENERIC_ZERO_MILITARY_SCORE_LABEL,)

    warship_combos = generate_ship_build_combos(
        _observation(warship_delta=1),
        **synthetic_catalog_context,
    )
    armed_warship_combos = [
        combo
        for combo in warship_combos
        if combo.warship_delta == 1 and combo.combo_id != GENERIC_FREIGHTER_COMBO_ID
    ]
    assert armed_warship_combos
    assert all(combo.score_delta_2x > 0 for combo in armed_warship_combos)
    assert not any(combo.combo_id == GENERIC_FREIGHTER_COMBO_ID for combo in warship_combos)


def test_unarmed_military_hull_has_zero_military_score(synthetic_catalog_context):
    hull = synthetic_catalog_context["hulls_by_id"][24]
    engine = synthetic_catalog_context["engines_by_id"][1]
    assert (
        ship_build_military_score_delta_2x(
            hull,
            engine,
            None,
            None,
            beam_count=0,
            launcher_count=0,
        )
        == 0
    )
    assert (
        ship_build_score_delta_2x(
            hull,
            engine,
            None,
            None,
            beam_count=0,
            launcher_count=0,
        )
        > 0
    )


def test_carrier_with_fighter_bays_scores_military_when_unarmed(synthetic_catalog_context):
    hull = synthetic_catalog_context["hulls_by_id"][71]
    engine = synthetic_catalog_context["engines_by_id"][1]
    assert ship_build_counts_as_warship(hull, beam_count=0, launcher_count=0)
    assert (
        ship_build_military_score_delta_2x(
            hull,
            engine,
            None,
            None,
            beam_count=0,
            launcher_count=0,
        )
        > 0
    )


def test_unarmed_escort_counts_as_freighter_on_scoreboard(synthetic_catalog_context):
    hull = synthetic_catalog_context["hulls_by_id"][24]
    assert not ship_build_counts_as_warship(hull, beam_count=0, launcher_count=0)

    context = {
        **synthetic_catalog_context,
        "buildable_hull_ids": frozenset({hull.id}),
    }
    combos = generate_ship_build_combos(
        _observation(military_delta_2x=0, warship_delta=0, freighter_delta=1),
        **context,
    )
    assert len(combos) == 1
    assert combos[0].combo_id == GENERIC_FREIGHTER_COMBO_ID


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
    assert (0, 0) not in beam_launcher_pairs


def test_multi_engine_hull_scales_engine_cost(synthetic_catalog_context):
    hull = synthetic_catalog_context["hulls_by_id"][71]
    engine = synthetic_catalog_context["engines_by_id"][1]
    engine_minerals = engine.tritanium + engine.duranium + engine.molybdenum
    hull_minerals = hull.tritanium + hull.duranium + hull.molybdenum
    expected = ship_construction_score_delta_2x(
        hull.cost + engine.cost * hull.engines,
        hull_minerals + engine_minerals * hull.engines,
    )
    assert (
        ship_build_score_delta_2x(
            hull,
            engine,
            None,
            None,
            beam_count=0,
            launcher_count=0,
        )
        == expected
    )
    assert hull.engines == 2

    combos = generate_ship_build_combos(
        _observation(warship_delta=1, freighter_delta=1),
        **synthetic_catalog_context,
    )
    carrier_combo = next(
        combo
        for combo in combos
        if combo.hull_id == 71 and combo.beam_count == 0 and combo.launcher_count == 0
    )
    assert carrier_combo.score_delta_2x == expected
    assert carrier_combo.warship_delta == 1
    assert any(combo.combo_id == GENERIC_FREIGHTER_COMBO_ID for combo in combos)


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
    assert beam_counts <= {hull.beams}


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
    assert beam_counts == {1, 2, 3, 4}
    assert launcher_counts == {1, 2, 3}


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


def test_solver_generic_freighter_produces_single_solution_without_expansion(
    synthetic_catalog_context,
):
    from api.analytics.military_score_inference.models import (
        InferenceProblem,
        InferenceSolutionShipBuild,
    )

    combos = generate_ship_build_combos(
        _observation(military_delta_2x=0, warship_delta=0, freighter_delta=1),
        **synthetic_catalog_context,
    )
    problem = InferenceProblem(
        observation=_observation(military_delta_2x=0, warship_delta=0, freighter_delta=1),
        aggregate_actions=(),
        ship_build_combos=combos,
        max_solutions=20,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 1
    assert result.solutions[0].ship_builds == (
        InferenceSolutionShipBuild(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            label=GENERIC_ZERO_MILITARY_SCORE_LABEL,
            count=1,
            hull_id=0,
            engine_id=0,
            beam_id=None,
            torp_id=None,
            beam_count=0,
            launcher_count=0,
        ),
    )


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
    assert objective_values == [0, -50]
    combo_ids = {solution.ship_builds[0].combo_id for solution in result.solutions}
    assert combo_ids == {"combo_high", "combo_low"}


def test_score_equivalent_expansion_prefers_top_k_by_probability():
    """Same score: expand to top K members by probability, not one per weight bucket."""
    from api.analytics.military_score_inference.models import InferenceProblem, ShipBuildCombo

    def _combo(combo_id: str, *, probability_weight: int) -> ShipBuildCombo:
        return ShipBuildCombo(
            combo_id=combo_id,
            hull_id=1,
            engine_id=1,
            beam_id=None,
            torp_id=None,
            beam_count=0,
            launcher_count=0,
            labels=(combo_id,),
            score_delta_2x=400,
            warship_delta=1,
            upper_bound=1,
            probability_weight=probability_weight,
        )

    combo_a = _combo("combo_a", probability_weight=85)
    combo_b = _combo("combo_b", probability_weight=85)
    combo_c = _combo("combo_c", probability_weight=85)
    combo_low = _combo("combo_low", probability_weight=80)
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
        ship_build_combos=(combo_a, combo_b, combo_c, combo_low),
        max_solutions=3,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    assert len(result.solutions) == 3
    combo_ids = [solution.ship_builds[0].combo_id for solution in result.solutions]
    assert combo_ids == ["combo_a", "combo_b", "combo_c"]
    assert all(solution.objective_value == 0 for solution in result.solutions)


def test_structural_top_k_not_flooded_by_score_equivalent_labels():
    """Solve budget is structural; label expansion must not crowd out other hits.

    One score-equivalent group with many low-prior labels used to consume
    ``max_solutions`` in a single CP-SAT iteration and block a second distinct
    military-exact structure from entering the held set.
    """
    from api.analytics.military_score_inference.models import InferenceProblem, ShipBuildCombo

    def _combo(
        combo_id: str,
        *,
        hull_id: int,
        score_delta_2x: int,
        probability_weight: int,
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
            score_delta_2x=score_delta_2x,
            warship_delta=1,
            upper_bound=1,
            probability_weight=probability_weight,
        )

    # Structure A: 600 + 400 (many equiv labels on the 600 class).
    equiv_600 = tuple(
        _combo(
            f"combo_600_{index}",
            hull_id=10 + index,
            score_delta_2x=600,
            probability_weight=100 - (10 * index),
        )
        for index in range(8)
    )
    combo_400 = _combo("combo_400", hull_id=2, score_delta_2x=400, probability_weight=100)
    # Structure B: 700 + 300 (distinct merged signature, slightly worse best prior).
    combo_700 = _combo("combo_700", hull_id=3, score_delta_2x=700, probability_weight=95)
    combo_300 = _combo("combo_300", hull_id=4, score_delta_2x=300, probability_weight=95)

    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=1000,
        warship_delta=2,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(),
        ship_build_combos=(*equiv_600, combo_400, combo_700, combo_300),
        max_solutions=3,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    assert result.diagnostics["structural_hit_count"] >= 2
    assert len(result.solutions) == 3
    held_combo_ids = {
        frozenset(build.combo_id for build in solution.ship_builds) for solution in result.solutions
    }
    assert frozenset({"combo_700", "combo_300"}) in held_combo_ids
    assert any("combo_600_" in combo_id for combo_ids in held_combo_ids for combo_id in combo_ids)


def test_near_best_objective_banding_skips_far_worse_structures():
    """Within-tier band keeps near-Z* hits and stops before far-worse exact matches."""
    from api.analytics.military_score_inference.models import InferenceProblem, ShipBuildCombo

    def _combo(
        combo_id: str,
        *,
        hull_id: int,
        score_delta_2x: int,
        probability_weight: int,
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
            score_delta_2x=score_delta_2x,
            warship_delta=1,
            upper_bound=1,
            probability_weight=probability_weight,
        )

    # Three distinct merged signatures for military 1000 / warships 2.
    # Ranking: A best (0), B near (-40), C far (-160). Band T=50 keeps A+B.
    structure_a = (
        _combo("a_hi", hull_id=1, score_delta_2x=600, probability_weight=100),
        _combo("a_lo", hull_id=2, score_delta_2x=400, probability_weight=100),
    )
    structure_b = (
        _combo("b_hi", hull_id=3, score_delta_2x=700, probability_weight=80),
        _combo("b_lo", hull_id=4, score_delta_2x=300, probability_weight=80),
    )
    structure_c = (
        _combo("c_hi", hull_id=5, score_delta_2x=550, probability_weight=20),
        _combo("c_lo", hull_id=6, score_delta_2x=450, probability_weight=20),
    )
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=1000,
        warship_delta=2,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(),
        ship_build_combos=(*structure_a, *structure_b, *structure_c),
        max_solutions=5,
        near_best_objective_threshold=50,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    assert result.diagnostics["tierMaxObjective"] == 0
    assert result.diagnostics["nearBestObjectiveThreshold"] == 50
    assert result.diagnostics["stopped_reason"] == "near_best_band_exhausted"
    assert result.diagnostics["structural_hit_count"] == 2
    held_ids = {
        frozenset(build.combo_id for build in solution.ship_builds) for solution in result.solutions
    }
    assert frozenset({"a_hi", "a_lo"}) in held_ids
    assert frozenset({"b_hi", "b_lo"}) in held_ids
    assert frozenset({"c_hi", "c_lo"}) not in held_ids


def test_seed_no_goods_skip_already_held_structures():
    """Prior-tier held solutions are no-gooded so search finds the next structure."""
    from api.analytics.military_score_inference.models import InferenceProblem, ShipBuildCombo

    def _combo(
        combo_id: str,
        *,
        hull_id: int,
        score_delta_2x: int,
        probability_weight: int,
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
            score_delta_2x=score_delta_2x,
            warship_delta=1,
            upper_bound=1,
            probability_weight=probability_weight,
        )

    structure_a = (
        _combo("a_hi", hull_id=1, score_delta_2x=600, probability_weight=100),
        _combo("a_lo", hull_id=2, score_delta_2x=400, probability_weight=100),
    )
    structure_b = (
        _combo("b_hi", hull_id=3, score_delta_2x=700, probability_weight=80),
        _combo("b_lo", hull_id=4, score_delta_2x=300, probability_weight=80),
    )
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=1000,
        warship_delta=2,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=(),
        ship_build_combos=(*structure_a, *structure_b),
        max_solutions=1,
    )
    first = solve_inference_problem(problem)
    assert first.status == STATUS_EXACT
    assert len(first.solutions) == 1
    first_ids = frozenset(build.combo_id for build in first.solutions[0].ship_builds)
    assert first_ids == frozenset({"a_hi", "a_lo"})

    second = solve_inference_problem(
        problem,
        seed_no_good_solutions=first.solutions,
    )
    assert second.status == STATUS_EXACT
    assert second.diagnostics["seedNoGoodCount"] == 1
    assert len(second.solutions) == 1
    second_ids = frozenset(build.combo_id for build in second.solutions[0].ship_builds)
    assert second_ids == frozenset({"b_hi", "b_lo"})


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
    specific_combos = [
        combo for combo in combos if not is_generic_zero_military_score_combo_id(combo.combo_id)
    ]
    assert {combo.hull_id for combo in specific_combos} <= context.buildable_hull_ids
    assert {combo.engine_id for combo in specific_combos} <= context.eligible_engine_ids
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
    # Terminal policy_step_id is the catalog that produced solutions (last
    # catalog-building tier). Soft-global steering may still walk later
    # zero-allowance skips, so the last attempted id need not match.
    assert payload["diagnostics"]["policy_step_id"] in policy_steps_attempted
    attempts = payload["diagnostics"].get("policy_step_attempts")
    if isinstance(attempts, list) and attempts:
        last_catalog_step = next(
            (
                entry
                for entry in reversed(attempts)
                if isinstance(entry, dict) and not entry.get("skipped")
            ),
            None,
        )
        if last_catalog_step is not None:
            assert last_catalog_step.get("policyStepId") == payload["diagnostics"]["policy_step_id"]
    assert catalog is not None
    assert payload["diagnostics"]["ship_build_combo_count"] > 0
    missouri_combo_id = "combo_13_9_3_6_8_6"
    all_ship_builds = [
        build for solution in payload["solutions"] for build in solution["shipBuilds"]
    ]
    assert any(build["comboId"] == missouri_combo_id for build in all_ship_builds)
    assert "accelerated_segments" in payload["diagnostics"]
