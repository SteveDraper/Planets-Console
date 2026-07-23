"""Tests for YAML inference search tier policy loading and catalog behavior."""

from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.military_score_inference.actions import (
    build_action_catalog,
    build_action_catalog_from_turn,
)
from api.analytics.military_score_inference.component_eligibility import (
    eligible_component_ids_for_filter,
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.models import (
    InferenceResult,
    InferenceSolution,
    InferenceSolutionShipBuild,
)
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import (
    ComponentFilter,
    compute_aggregate_admission_caps,
    default_tier_policy_path,
    parse_solver_thresholds,
    parse_tier_policy_steps,
    resolve_solver_thresholds,
    resolve_tier_policies,
)
from api.models.components import Engine

from tests.fixtures.military_score_inference import _observation, legacy_fleet_torp_overlay

REPO_ROOT = Path(__file__).resolve().parents[3]


def _emit_mock_solver_solutions(result: InferenceResult, **kwargs) -> InferenceResult:
    on_solution = kwargs.get("on_solution")
    if on_solution is not None:
        for solution in result.solutions:
            on_solution(solution)
    return result


def test_default_policy_path_exists():
    path = default_tier_policy_path()
    assert path.is_file()
    assert path == REPO_ROOT / "assets/analytics/scores/tier_policy.yaml"


def test_policy_loader_validates_final_alpha_zero():
    steps = resolve_tier_policies()
    assert steps[-1].alpha == 0
    assert steps[0].id == "early_game_bands"
    assert steps[1].id == "widen_launchers"
    assert steps[2].id == "collision_hull_widen"
    assert [step.id for step in steps[3:7]] == [
        "widen_hulls",
        "admit_ship_torpedoes",
        "modest_planet_defense",
        "full_components",
    ]
    assert steps[0].allow_ship_only_exact_early_stop is False
    assert steps[1].allow_ship_only_exact_early_stop is False
    assert steps[2].allow_ship_only_exact_early_stop is False
    assert all(not step.allow_ship_only_exact_early_stop for step in steps[:6])
    assert all(step.allow_ship_only_exact_early_stop for step in steps[6:])
    assert steps[2].hull_collision_twin_widen is True
    assert sum(1 for step in steps if step.hull_collision_twin_widen) == 1
    assert all(step.near_best_objective_threshold == 250 for step in steps)
    torps = next(step for step in steps if step.id == "admit_ship_torpedoes")
    assert torps.min_seconds == 3.0
    assert torps.max_seconds == 8.0
    full = next(step for step in steps if step.id == "full_components")
    assert full.max_seconds == 5.0


def test_policy_loader_reads_aggregate_probability_bins():
    from api.analytics.military_score_inference.tier_policy import (
        aggregate_bin_bounds_for_key,
        resolve_aggregate_probability_bins,
    )

    bins = resolve_aggregate_probability_bins()
    assert "planet_defense_posts_added_total" in bins
    assert bins["planet_defense_posts_added_total"][0].upper_count == 0
    assert aggregate_bin_bounds_for_key("ship_torps_per_type")[1].upper_count == 40


def test_policy_loader_reads_solver_thresholds():
    thresholds = resolve_solver_thresholds()
    assert thresholds.ship_only_exact_early_stop_min_plausibility == -300
    assert thresholds.no_new_exact_signatures_early_stop_min_plausibility == -300


def test_policy_loader_rejects_non_int_solver_threshold():
    with pytest.raises(ValueError, match="shipOnlyExactEarlyStopMinPlausibility must be an int"):
        parse_solver_thresholds(
            {
                "solverThresholds": {
                    "shipOnlyExactEarlyStopMinPlausibility": "-300",
                    "noNewExactSignaturesEarlyStopMinPlausibility": -300,
                }
            }
        )


def test_policy_loader_rejects_invalid_near_best_objective_threshold():
    document = {
        "steps": [
            {
                "id": "invalid",
                "filters": {
                    "hulls": {"all": True},
                    "engines": {"all": True},
                    "beams": {"all": True},
                    "launchers": {"all": True},
                },
                "alpha": 0,
                "nearBestObjectiveThreshold": -1,
            }
        ]
    }
    with pytest.raises(ValueError, match="nearBestObjectiveThreshold"):
        parse_tier_policy_steps(document)


def test_policy_loader_rejects_non_int_no_new_exact_signatures_threshold():
    with pytest.raises(
        ValueError, match="noNewExactSignaturesEarlyStopMinPlausibility must be an int"
    ):
        parse_solver_thresholds(
            {
                "solverThresholds": {
                    "shipOnlyExactEarlyStopMinPlausibility": -300,
                    "noNewExactSignaturesEarlyStopMinPlausibility": "-300",
                }
            }
        )


def test_policy_loader_rejects_non_superset_tech_levels():
    document = {
        "steps": [
            {
                "id": "narrow",
                "filters": {
                    "hulls": {"techLevels": [1, 2]},
                    "engines": {"techLevels": [1]},
                    "beams": {"techLevels": [1]},
                    "launchers": {"techLevels": [1]},
                },
                "alpha": 0,
            },
            {
                "id": "too_narrow",
                "filters": {
                    "hulls": {"techLevels": [1]},
                    "engines": {"techLevels": [1]},
                    "beams": {"techLevels": [1]},
                    "launchers": {"techLevels": [1]},
                },
                "alpha": 0,
            },
        ]
    }
    with pytest.raises(ValueError, match="superset"):
        parse_tier_policy_steps(document)


def test_policy_loader_rejects_all_and_tech_levels_together():
    document = {
        "steps": [
            {
                "id": "invalid",
                "filters": {
                    "hulls": {"all": True, "techLevels": [1]},
                    "engines": {"all": True},
                    "beams": {"all": True},
                    "launchers": {"all": True},
                },
                "alpha": 0,
            }
        ]
    }
    with pytest.raises(ValueError, match="cannot set both all and techLevels"):
        parse_tier_policy_steps(document)


def test_policy_loader_rejects_missing_tech_levels_when_all_false():
    document = {
        "steps": [
            {
                "id": "invalid",
                "filters": {
                    "hulls": {"techLevels": [1]},
                    "engines": {},
                    "beams": {"all": True},
                    "launchers": {"all": True},
                },
                "alpha": 0,
            }
        ]
    }
    with pytest.raises(ValueError, match="filters.engines.techLevels"):
        parse_tier_policy_steps(document)


def test_policy_loader_rejects_missing_final_alpha_zero():
    document = {
        "steps": [
            {
                "id": "banded",
                "filters": {
                    "hulls": {"techLevels": [1]},
                    "engines": {"techLevels": [1]},
                    "beams": {"techLevels": [1]},
                    "launchers": {"techLevels": [1]},
                },
                "alpha": 10,
            }
        ]
    }
    with pytest.raises(ValueError, match="alpha: 0"):
        parse_tier_policy_steps(document)


def test_resolve_tier_policies_returns_yaml_steps():
    steps = resolve_tier_policies()
    assert len(steps) == 10


def test_early_step_uses_tech_level_bands_not_lowest_component_id(sample_turn):
    observation = _observation(warship_delta=1, freighter_delta=1, starbases_owned=5)
    early_step = resolve_tier_policies()[0]
    context = turn_catalog_context_for_policy_step(sample_turn, observation.player_id, early_step)
    hulls_at_allowed_tech = {
        hull.id
        for hull in sample_turn.hulls
        if hull.techlevel in early_step.filters.hulls.tech_levels
    }
    beams_at_allowed_tech = {
        beam.id
        for beam in sample_turn.beams
        if beam.techlevel in early_step.filters.beams.tech_levels
    }
    launchers_at_allowed_tech = {
        torp.id
        for torp in sample_turn.torpedos
        if torp.techlevel in early_step.filters.launchers.tech_levels
    }
    assert early_step.filters.engines.all
    assert context.buildable_hull_ids <= hulls_at_allowed_tech
    assert context.eligible_beam_ids <= beams_at_allowed_tech
    assert context.eligible_torp_ids <= launchers_at_allowed_tech
    assert len(context.buildable_hull_ids) >= 1


def test_hulls_all_filter_uses_buildable_set_without_tech_band(sample_turn):
    observation = _observation(warship_delta=1, freighter_delta=1, starbases_owned=5)
    full_step = resolve_tier_policies()[-1]
    early_step = resolve_tier_policies()[0]
    full_context = turn_catalog_context_for_policy_step(
        sample_turn,
        observation.player_id,
        full_step,
    )
    early_context = turn_catalog_context_for_policy_step(
        sample_turn,
        observation.player_id,
        early_step,
    )
    assert full_step.filters.hulls.all
    assert len(full_context.buildable_hull_ids) >= len(early_context.buildable_hull_ids)


def test_slack_deferred_on_early_steps(sample_turn):
    observation = _observation(military_delta_2x=500)
    early_catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=resolve_tier_policies()[0],
        policy_step_index=0,
    )
    action_ids = {action.id for action in early_catalog.aggregate_actions}
    assert "planet_defense_posts_added_total" not in action_ids
    assert "starbase_defense_posts_added_total" not in action_ids
    assert not any(action_id.startswith("ship_torps_loaded_") for action_id in action_ids)
    assert "fighters_starbase_to_ship" not in action_ids
    assert "fighters_ship_to_starbase" not in action_ids
    assert "starbase_fighters_added_total" not in action_ids
    assert "ship_fighters_added_total" not in action_ids


def test_full_components_step_opens_ship_slots_before_heavier_aggregates(sample_turn):
    observation = _observation(warship_delta=1, freighter_delta=1, starbases_owned=5)
    widen_hulls = next(step for step in resolve_tier_policies() if step.id == "widen_hulls")
    full_components = next(step for step in resolve_tier_policies() if step.id == "full_components")
    widen_catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=widen_hulls,
    )
    full_components_catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=full_components,
    )
    assert full_components.beam_slot_counts == "partial"
    assert full_components.launcher_slot_counts == "partial"
    # Monotonic allowlist retains prior high-prior aggregates; fighters still deferred.
    assert "ship_torps_per_type" in full_components.aggregate_allowlist
    assert "planet_defense_posts_added_total" in full_components.aggregate_allowlist
    action_ids = {action.id for action in full_components_catalog.aggregate_actions}
    assert "starbase_fighters_added_total" not in action_ids
    assert "ship_fighters_added_total" not in action_ids
    assert "fighters_starbase_to_ship" not in action_ids
    assert "fighters_ship_to_starbase" not in action_ids
    assert len(full_components_catalog.ship_build_combos) >= len(widen_catalog.ship_build_combos)


def test_fighter_builds_admitted_on_starbase_defense_step_with_caps(sample_turn):
    observation = _observation(military_delta_2x=500)
    full_components_step = next(
        step for step in resolve_tier_policies() if step.id == "admit_starbase_defense_posts"
    )
    catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=full_components_step,
    )
    starbase_fighters = next(
        action
        for action in catalog.aggregate_actions
        if action.id == "starbase_fighters_added_total"
    )
    ship_fighters = next(
        action for action in catalog.aggregate_actions if action.id == "ship_fighters_added_total"
    )
    assert starbase_fighters.upper_bound <= 50
    assert ship_fighters.upper_bound <= 20


def test_ship_torpedoes_admitted_after_full_components_with_caps(sample_turn):
    observation = _observation(military_delta_2x=500)
    torp_step = next(step for step in resolve_tier_policies() if step.id == "admit_ship_torpedoes")
    catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=torp_step,
        fleet_torp_overlay=legacy_fleet_torp_overlay(),
    )
    action_ids = {action.id for action in catalog.aggregate_actions}
    assert "planet_defense_posts_added_total" not in action_ids
    assert "starbase_fighters_added_total" not in action_ids
    torp_actions = [
        action for action in catalog.aggregate_actions if action.id.startswith("ship_torps_loaded_")
    ]
    assert torp_actions
    assert all(action.upper_bound <= 40 for action in torp_actions)


def test_slack_admitted_on_later_steps_with_caps(sample_turn):
    observation = _observation(military_delta_2x=500)
    defense_step = next(
        step for step in resolve_tier_policies() if step.id == "modest_planet_defense"
    )
    catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=defense_step,
        fleet_torp_overlay=legacy_fleet_torp_overlay(),
    )
    planet_action = next(
        action
        for action in catalog.aggregate_actions
        if action.id == "planet_defense_posts_added_total"
    )
    torp_actions = [
        action for action in catalog.aggregate_actions if action.id.startswith("ship_torps_loaded_")
    ]
    assert planet_action.upper_bound <= 16
    assert torp_actions
    assert all(action.upper_bound <= 40 for action in torp_actions)


def test_restricted_activetorps_limits_ship_torpedo_aggregate_actions(sample_turn):
    observation = _observation(military_delta_2x=500)
    player_id = observation.player_id
    restricted_player = replace(sample_turn.player, activetorps="1")
    turn = replace(
        sample_turn,
        player=restricted_player,
        players=[
            restricted_player if player.id == player_id else player
            for player in sample_turn.players
        ],
    )
    torp_step = next(step for step in resolve_tier_policies() if step.id == "admit_ship_torpedoes")
    catalog_context = turn_catalog_context_for_policy_step(turn, player_id, torp_step)

    assert catalog_context.eligible_torp_ids == frozenset({1})
    assert len(catalog_context.torpedos_by_id) > 1

    catalog = build_action_catalog_from_turn(
        observation,
        turn,
        policy_step=torp_step,
        fleet_torp_overlay=legacy_fleet_torp_overlay(),
    )

    torp_action_ids = {
        action.id
        for action in catalog.aggregate_actions
        if action.id.startswith("ship_torps_loaded_")
    }
    assert torp_action_ids == {"ship_torps_loaded_1"}


def test_tech_level_filtering_derives_component_sets(synthetic_catalog_context):
    early_step = resolve_tier_policies()[0]
    high_tech_engine = Engine(
        id=99,
        name="High Tech",
        cost=99,
        tritanium=1,
        duranium=1,
        molybdenum=1,
        techlevel=5,
        warp1=1,
        warp2=1,
        warp3=1,
        warp4=1,
        warp5=1,
        warp6=1,
        warp7=1,
        warp8=1,
        warp9=1,
    )
    engines_by_id = {
        **synthetic_catalog_context["engines_by_id"],
        high_tech_engine.id: high_tech_engine,
    }
    beam_filter = early_step.filters.beams
    eligible_beam_ids = eligible_component_ids_for_filter(
        beam_filter,
        active_component_csv="",
        components_by_id=synthetic_catalog_context["beams_by_id"],
    )
    context = {
        key: value for key, value in synthetic_catalog_context.items() if key != "prior_catalog"
    }
    context |= {
        "engines_by_id": engines_by_id,
        "eligible_beam_ids": eligible_beam_ids,
    }
    from tests.fixtures.military_score_inference_prior_weights import minimal_prior_catalog

    early_catalog = build_action_catalog(
        _observation(warship_delta=1),
        policy_step=early_step,
        prior_catalog=minimal_prior_catalog(),
        **context,
    )
    assert high_tech_engine.id not in {combo.engine_id for combo in early_catalog.ship_build_combos}


def test_component_ids_restriction_is_applied_when_present(synthetic_catalog_context):
    restricted_filter = ComponentFilter(all=False, tech_levels=(1,), component_ids=(1,))
    eligible_beam_ids = eligible_component_ids_for_filter(
        restricted_filter,
        active_component_csv="",
        components_by_id=synthetic_catalog_context["beams_by_id"],
    )
    assert eligible_beam_ids == frozenset({1})


def test_include_component_ids_unions_into_tech_band():
    from api.models.components import Beam

    beams_by_id = {
        1: Beam(
            id=1,
            name="Laser",
            cost=1,
            tritanium=1,
            duranium=0,
            molybdenum=0,
            mass=1,
            techlevel=1,
            crewkill=1,
            damage=1,
        ),
        10: Beam(
            id=10,
            name="Heavy Phaser",
            cost=1,
            tritanium=1,
            duranium=0,
            molybdenum=0,
            mass=1,
            techlevel=10,
            crewkill=1,
            damage=1,
        ),
    }
    tech1 = eligible_component_ids_for_filter(
        ComponentFilter(all=False, tech_levels=(1,)),
        active_component_csv="",
        components_by_id=beams_by_id,
    )
    widened = eligible_component_ids_for_filter(
        ComponentFilter(all=False, tech_levels=(1,), include_component_ids=(10,)),
        active_component_csv="",
        components_by_id=beams_by_id,
    )
    assert tech1 == frozenset({1})
    assert widened == frozenset({1, 10})


def test_solve_with_policy_ladder_stops_when_no_new_exact_signatures(sample_turn, monkeypatch):
    observation = _observation(warship_delta=1, starbases_owned=3)
    solution_a = InferenceSolution(objective_value=100, actions=(), ship_builds=())
    solution_b = InferenceSolution(
        objective_value=50,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="combo_a",
                label="Build A",
                count=1,
                hull_id=1,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )
    policy_steps = resolve_tier_policies()
    early = policy_steps[0]
    widen_launchers = next(step for step in policy_steps if step.id == "widen_launchers")
    collision = next(step for step in policy_steps if step.id == "collision_hull_widen")
    widen_hulls = next(step for step in policy_steps if step.id == "widen_hulls")
    call_step_ids: list[str] = []

    def _solve_side_effect(problem, **kwargs):
        call_step_ids.append(problem.policy_step_id)
        if problem.policy_step_id == early.id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        if problem.policy_step_id == widen_launchers.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(solution_a,),
                    diagnostics={"policy_step_id": widen_launchers.id},
                ),
                **kwargs,
            )
        if problem.policy_step_id == widen_hulls.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(solution_a, solution_b),
                    diagnostics={"policy_step_id": widen_hulls.id},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(solution_a,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step."
        "_solution_qualifies_for_ship_only_exact_early_stop",
        lambda *args, **kwargs: False,
    )
    result, catalog, problem, attempted, step_diagnostics = solve_with_policy_ladder(
        observation,
        sample_turn,
    )

    assert attempted[:4] == [early.id, widen_launchers.id, collision.id, widen_hulls.id]
    assert call_step_ids[0] == early.id
    assert widen_launchers.id in call_step_ids
    assert collision.id not in call_step_ids  # skipped when no twin partners
    assert widen_hulls.id in call_step_ids
    assert [solution.objective_value for solution in result.solutions] == [100, 50]
    assert catalog.policy_step_id == "admit_ship_torpedoes"
    assert problem.policy_step_id == "admit_ship_torpedoes"
    assert step_diagnostics
    assert step_diagnostics[0]["policyStepId"] == early.id
    assert "filters" in step_diagnostics[0]["constraintSnapshot"]
    assert "durationMs" in step_diagnostics[0]
    assert step_diagnostics[0]["heldCountBefore"] == 0
    assert step_diagnostics[0]["newlyAdmittedCount"] == 0
    widen_diag = next(
        diag for diag in step_diagnostics if diag["policyStepId"] == widen_launchers.id
    )
    assert widen_diag["newlyAdmittedCount"] >= 1
    assert widen_diag["newlyAdmitted"][0]["objectiveValue"] == 100
    assert step_diagnostics[-1].get("ladderEarlyStopReason") == "no_new_exact_signatures"
    assert result.diagnostics["stopped_reason"] == "no_new_exact_signatures"


def test_solve_with_policy_ladder_continues_no_new_signatures_when_best_below_threshold(
    sample_turn, monkeypatch
):
    """#236: implausible held exacts must not cut off later aggregate-widening tiers."""
    observation = _observation(warship_delta=1, starbases_owned=3)
    # Below noNewExactSignaturesEarlyStopMinPlausibility (-300); mirrors issue repro.
    weak_exact = InferenceSolution(
        objective_value=-1133,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="combo_weak",
                label="Weak exact",
                count=1,
                hull_id=1,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )
    later_exact = InferenceSolution(
        objective_value=-200,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="combo_later",
                label="Later exact",
                count=1,
                hull_id=1,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )
    policy_steps = resolve_tier_policies()
    early = policy_steps[0]
    widen_launchers = next(step for step in policy_steps if step.id == "widen_launchers")
    widen_hulls = next(step for step in policy_steps if step.id == "widen_hulls")
    planet_defense = next(step for step in policy_steps if step.id == "modest_planet_defense")

    def _solve_side_effect(problem, **kwargs):
        if problem.policy_step_id == early.id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        if problem.policy_step_id in {widen_launchers.id, widen_hulls.id, "full_components"}:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(weak_exact,),
                    diagnostics={"policy_step_id": problem.policy_step_id},
                ),
                **kwargs,
            )
        if problem.policy_step_id == planet_defense.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(later_exact,),
                    diagnostics={"policy_step_id": problem.policy_step_id},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(weak_exact,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step."
        "_solution_qualifies_for_ship_only_exact_early_stop",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
    )

    # Empty-belief admit_ship_torpedoes is a catalog no-op, but the weak held exact
    # is below the plausibility floor so the ladder must continue into aggregate tiers.
    assert "admit_ship_torpedoes" in attempted
    assert "modest_planet_defense" in attempted
    assert [solution.objective_value for solution in result.solutions] == [-200, -1133]


def test_solve_with_policy_ladder_continues_when_aggregate_actions_are_added(
    sample_turn, monkeypatch
):
    observation = _observation(warship_delta=1)
    policy_steps = resolve_tier_policies()
    early = policy_steps[0]
    widen_launchers = next(step for step in policy_steps if step.id == "widen_launchers")
    widen_hulls = next(step for step in policy_steps if step.id == "widen_hulls")
    full_components = next(step for step in policy_steps if step.id == "full_components")
    solution_a = InferenceSolution(
        objective_value=100,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="combo_a",
                label="Build A",
                count=1,
                hull_id=1,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )
    solution_b = InferenceSolution(
        objective_value=50,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="combo_b",
                label="Build B",
                count=1,
                hull_id=1,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )
    solution_c = InferenceSolution(
        objective_value=75,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="combo_c",
                label="Build C",
                count=1,
                hull_id=1,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )

    def _solve_side_effect(problem, **kwargs):
        if problem.policy_step_id == early.id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        if problem.policy_step_id == widen_launchers.id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_EXACT, solutions=(solution_a,), diagnostics={}),
                **kwargs,
            )
        if problem.policy_step_id == widen_hulls.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(solution_a, solution_b),
                    diagnostics={"policy_step_id": problem.policy_step_id},
                ),
                **kwargs,
            )
        if problem.policy_step_id == full_components.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(solution_c,),
                    diagnostics={"policy_step_id": problem.policy_step_id},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(solution_a,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step."
        "_solution_qualifies_for_ship_only_exact_early_stop",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    result, catalog, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        fleet_torp_overlay=legacy_fleet_torp_overlay(),
    )

    assert "admit_ship_torpedoes" in attempted
    assert "modest_planet_defense" in attempted
    assert result.status == STATUS_EXACT


def test_solve_with_policy_ladder_reports_exact_when_top_solution_satisfies_hard_equalities(
    sample_turn, monkeypatch
):
    from api.analytics.military_score_inference.solver import STATUS_TIME_LIMITED

    observation = _observation(military_delta_2x=400, warship_delta=1)
    exact_solution = InferenceSolution(
        objective_value=100,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id="combo_a",
                label="Build A",
                count=1,
                hull_id=1,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )

    def _solve_side_effect(problem, **kwargs):
        if problem.military_score_alpha > 0:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_TIME_LIMITED,
                    solutions=(exact_solution,),
                    diagnostics={"policy_step_id": problem.policy_step_id},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(exact_solution,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder.solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    result, _, _, _, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        time_limit_seconds=60.0,
    )

    assert result.status == STATUS_EXACT


def _ship_build_solution(
    *,
    combo_id: str,
    objective_value: int,
    label: str | None = None,
    hull_id: int = 1,
):
    return InferenceSolution(
        objective_value=objective_value,
        actions=(),
        ship_builds=(
            InferenceSolutionShipBuild(
                combo_id=combo_id,
                label=label or combo_id,
                count=1,
                hull_id=hull_id,
                engine_id=1,
                beam_id=None,
                torp_id=None,
                beam_count=0,
                launcher_count=0,
            ),
        ),
    )


def test_solve_with_policy_ladder_retains_exact_across_combo_widen(sample_turn, monkeypatch):
    observation = _observation(warship_delta=1)
    policy_steps = resolve_tier_policies()
    widen_launchers = next(step for step in policy_steps if step.id == "widen_launchers")
    collision = next(step for step in policy_steps if step.id == "collision_hull_widen")
    early_solution = _ship_build_solution(combo_id="combo_early", objective_value=100)

    def _solve_side_effect(problem, **kwargs):
        if problem.policy_step_id == policy_steps[0].id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        if problem.policy_step_id == widen_launchers.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(early_solution,),
                    diagnostics={"policy_step_id": widen_launchers.id},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_NO_EXACT_SOLUTION,
                solutions=(),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
    )

    assert widen_launchers.id in attempted
    assert collision.id in attempted
    assert any(solution.ship_builds[0].combo_id == "combo_early" for solution in result.solutions)


def test_solve_with_policy_ladder_evicts_worst_when_k_best_full(sample_turn, monkeypatch):
    observation = _observation(warship_delta=1)
    policy_steps = resolve_tier_policies()
    widen_launchers = next(step for step in policy_steps if step.id == "widen_launchers")
    widen_hulls = next(step for step in policy_steps if step.id == "widen_hulls")
    low_solution = _ship_build_solution(combo_id="combo_low", objective_value=40)
    mid_solution = _ship_build_solution(combo_id="combo_mid", objective_value=50)
    high_solution = _ship_build_solution(combo_id="combo_high", objective_value=100)

    def _solve_side_effect(problem, **kwargs):
        if problem.policy_step_id == policy_steps[0].id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        if problem.policy_step_id == widen_launchers.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(mid_solution, low_solution),
                    diagnostics={"policy_step_id": widen_launchers.id},
                ),
                **kwargs,
            )
        if problem.policy_step_id == widen_hulls.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(high_solution,),
                    diagnostics={"policy_step_id": widen_hulls.id},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_NO_EXACT_SOLUTION,
                solutions=(),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step."
        "_solution_qualifies_for_ship_only_exact_early_stop",
        lambda *args, **kwargs: False,
    )
    result, _, _, _, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        max_solutions=2,
    )

    assert [solution.objective_value for solution in result.solutions] == [100, 50]
    assert {solution.ship_builds[0].combo_id for solution in result.solutions} == {
        "combo_high",
        "combo_mid",
    }


def test_solve_with_policy_ladder_defers_ship_only_early_stop_past_early_bands(
    sample_turn, monkeypatch
):
    """Ship-only exact that meets plausibility must not stop on early ladder steps.

    Steps through ``modest_planet_defense`` set ``allowShipOnlyExactEarlyStop: false``;
    a qualifying exact on early bands must still reach ``admit_ship_torpedoes`` /
    later aggregate steps before ship-only early-stop is armed.
    """
    observation = _observation(military_delta_2x=400, warship_delta=1)
    policy_steps = resolve_tier_policies()
    early = policy_steps[0]
    widen_launchers = next(step for step in policy_steps if step.id == "widen_launchers")
    collision = next(step for step in policy_steps if step.id == "collision_hull_widen")
    assert early.id == "early_game_bands"
    assert early.allow_ship_only_exact_early_stop is False
    assert widen_launchers.allow_ship_only_exact_early_stop is False
    assert collision.allow_ship_only_exact_early_stop is False

    early_exact = _ship_build_solution(combo_id="combo_early", objective_value=-300)
    widen_exact = _ship_build_solution(combo_id="combo_widen", objective_value=-300)

    def _solve_side_effect(problem, **kwargs):
        solution = early_exact if problem.policy_step_id == early.id else widen_exact
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(solution,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    _, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        time_limit_seconds=60.0,
    )

    assert attempted[:3] == [early.id, widen_launchers.id, collision.id]


def test_solve_with_policy_ladder_runs_collision_hull_widen_on_twin_hit(sample_turn, monkeypatch):
    """When held exact emits a low hull with an epic twin, collision step must solve.

    Valiant (hull 30) at military change 2749 admits Resolute (31); the ladder must
    invoke the solver for ``collision_hull_widen`` (not only record a skip).
    """
    observation = _observation(military_delta_2x=5498, warship_delta=1)
    policy_steps = resolve_tier_policies()
    early = policy_steps[0]
    widen_launchers = next(step for step in policy_steps if step.id == "widen_launchers")
    collision = next(step for step in policy_steps if step.id == "collision_hull_widen")
    valiant = _ship_build_solution(
        combo_id="valiant",
        objective_value=-171,
        label="Valiant",
        hull_id=30,
    )
    call_step_ids: list[str] = []

    def _solve_side_effect(problem, **kwargs):
        call_step_ids.append(problem.policy_step_id)
        if problem.policy_step_id == early.id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        if problem.policy_step_id == widen_launchers.id:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(valiant,),
                    diagnostics={"policy_step_id": widen_launchers.id},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(valiant,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step."
        "_solution_qualifies_for_ship_only_exact_early_stop",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.collision_hull_widen.buildable_hull_ids_for_player",
        lambda *args, **kwargs: frozenset({29, 30, 31, 106}),
    )
    _, _, _, attempted, step_diagnostics = solve_with_policy_ladder(
        observation,
        sample_turn,
        time_limit_seconds=60.0,
    )

    assert collision.id in attempted
    assert collision.id in call_step_ids
    collision_diag = next(diag for diag in step_diagnostics if diag["policyStepId"] == collision.id)
    collision_widen = collision_diag["collisionHullWiden"]
    assert collision_widen["skipped"] is False
    assert collision_widen["admittedHighHullIds"] == [31]
    assert collision_widen["emittedLowHullIds"] == [30]
    assert collision_widen["militaryChange"] == 2749
    hull_snapshot = collision_diag["constraintSnapshot"]["filters"]["hulls"]
    assert hull_snapshot["includeComponentIds"] == [31]


def test_solve_with_policy_ladder_stops_when_ship_only_exact_meets_plausibility_threshold(
    sample_turn, monkeypatch
):
    observation = _observation(military_delta_2x=400, warship_delta=1)
    policy_steps = resolve_tier_policies()
    first_early_stop_step = next(
        step for step in policy_steps if step.allow_ship_only_exact_early_stop
    )
    assert first_early_stop_step.id == "full_components"

    def _solve_side_effect(problem, **kwargs):
        if problem.policy_step_id == policy_steps[0].id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        # Distinct combo ids per step so #236 no-new-signatures does not fire first.
        threshold_solution = _ship_build_solution(
            combo_id=f"combo_{problem.policy_step_id}",
            objective_value=-300,
        )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(threshold_solution,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    _, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        time_limit_seconds=60.0,
    )

    expected = [step.id for step in policy_steps if not step.allow_ship_only_exact_early_stop]
    expected.append(first_early_stop_step.id)
    assert attempted == expected


def test_solve_with_policy_ladder_continues_when_ship_only_exact_below_plausibility_threshold(
    sample_turn, monkeypatch
):
    observation = _observation(military_delta_2x=400, warship_delta=1)
    policy_steps = resolve_tier_policies()
    low_plaus_solution = _ship_build_solution(combo_id="combo_a", objective_value=-301)

    def _solve_side_effect(problem, **kwargs):
        if problem.policy_step_id == policy_steps[0].id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(low_plaus_solution,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    _, _, _, attempted_low, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        time_limit_seconds=60.0,
    )

    threshold_solution = _ship_build_solution(combo_id="combo_a", objective_value=-300)

    def _solve_side_effect_at_threshold(problem, **kwargs):
        if problem.policy_step_id == policy_steps[0].id:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(threshold_solution,),
                diagnostics={"policy_step_id": problem.policy_step_id},
            ),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect_at_threshold,
    )
    _, _, _, attempted_at_threshold, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        time_limit_seconds=60.0,
    )

    assert len(attempted_low) > len(attempted_at_threshold)


def test_full_catalog_step_applies_tier_overflow_to_planet_defense(sample_turn):
    steps = resolve_tier_policies()
    full_catalog_index = next(
        index for index, step in enumerate(steps) if step.id == "full_catalog_exact"
    )
    full_step = steps[full_catalog_index]
    observation = _observation(military_delta_2x=500)
    catalog = build_action_catalog_from_turn(
        observation,
        sample_turn,
        policy_step=full_step,
        policy_step_index=full_catalog_index,
    )

    assert catalog.admission_caps_by_action_id["planet_defense_posts_added_total"] == 16
    assert "planet_defense_posts_added_total" in catalog.tier_overflow_by_action_id
    overflow = catalog.tier_overflow_by_action_id["planet_defense_posts_added_total"]
    assert overflow.marginal_weight == 50


def test_compute_aggregate_admission_caps_records_first_step_appearance():
    steps = resolve_tier_policies()
    torp_step_index = next(
        index for index, step in enumerate(steps) if step.id == "admit_ship_torpedoes"
    )
    caps = compute_aggregate_admission_caps(steps, torp_step_index)

    assert caps == {"ship_torps_per_type": 40}

    starbase_step_index = next(
        index for index, step in enumerate(steps) if step.id == "admit_starbase_defense_posts"
    )
    caps = compute_aggregate_admission_caps(steps, starbase_step_index)

    assert caps["planet_defense_posts_added_total"] == 16
    assert caps["ship_torps_per_type"] == 40
    assert caps["starbase_defense_posts_added_total"] == 5
