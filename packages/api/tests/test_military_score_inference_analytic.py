"""Tests for military score inference integration with the scores analytic."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import (
    STATUS_SOLVER_ERROR,
    build_inference_observation,
    infer_military_score_build,
    inference_result_to_api_payload,
    is_after_ship_limit,
    observation_to_constraints_payload,
    prior_turn_score_data_available,
)
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.score_arithmetic import (
    solution_military_score_arithmetic_payload,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    solve_inference_problem,
)
from api.analytics.scores import get_scores_row_inference, get_scores_table


@pytest.fixture
def first_turn(sample_turn):
    return replace(
        sample_turn,
        settings=replace(sample_turn.settings, turn=1),
    )


def test_scores_output_unchanged_when_inference_disabled(sample_turn):
    disabled = get_scores_table(sample_turn)
    default_options = get_scores_table(sample_turn, TurnAnalyticsOptions())
    assert disabled == default_options
    assert "inference" not in disabled["rows"][0]


def test_scores_table_never_includes_inference(sample_turn):
    data = get_scores_table(
        sample_turn,
        TurnAnalyticsOptions(),
    )
    assert "inference" not in data["rows"][0]


def test_scores_row_inference_returns_solver_payload(sample_turn):
    player_id = sample_turn.scores[0].ownerid
    inference = get_scores_row_inference(sample_turn, player_id)
    assert inference["playerId"] == player_id
    assert inference["status"] in {
        STATUS_EXACT,
        STATUS_INVALID_PROBLEM,
        "no_exact_solution",
        "time_limited",
    }
    assert isinstance(inference["summary"], str)
    assert inference["solutionCount"] == len(inference["solutions"])
    assert "catalog_size" in inference["diagnostics"]


def test_first_turn_produces_no_prior_turn_status(first_turn):
    score = first_turn.scores[0]
    inference = infer_military_score_build(score, first_turn)
    assert inference["status"] == STATUS_NO_PRIOR_TURN
    assert inference["summary"] == "Prior turn score data unavailable"
    assert inference["diagnostics"]["reason"] == "first_turn"


def test_first_turn_row_inference_produces_no_prior_turn_status(first_turn):
    score = first_turn.scores[0]
    inference = get_scores_row_inference(first_turn, score.ownerid)
    assert inference["status"] == STATUS_NO_PRIOR_TURN
    assert inference["summary"] == "Prior turn score data unavailable"
    assert inference["diagnostics"]["reason"] == "first_turn"


def test_build_inference_observation_maps_score_deltas(sample_turn):
    score = sample_turn.scores[0]
    observation = build_inference_observation(score, sample_turn)
    assert observation.player_id == score.ownerid
    assert observation.turn == sample_turn.settings.turn
    assert observation.military_delta_2x == 2 * score.militarychange
    assert observation.warship_delta == score.shipchange
    assert observation.freighter_delta == score.freighterchange
    assert observation.priority_point_delta == score.prioritypointchange
    assert observation.starbases_owned == score.starbases


def test_prior_turn_score_data_available(sample_turn, first_turn):
    assert prior_turn_score_data_available(sample_turn) is True
    assert prior_turn_score_data_available(first_turn) is False


def test_is_after_ship_limit_uses_game_total_for_standard_queue(sample_turn):
    score = sample_turn.scores[0]
    assert is_after_ship_limit(sample_turn, score) is False

    over_limit_turn = replace(
        sample_turn,
        settings=replace(sample_turn.settings, shiplimit=10),
    )
    assert is_after_ship_limit(over_limit_turn, score) is True


def test_solver_failure_is_isolated_per_player(sample_turn):
    failing_player_id = sample_turn.scores[0].ownerid

    def _solve_side_effect(problem):
        if problem.observation.player_id == failing_player_id:
            raise RuntimeError("solver exploded")
        return solve_inference_problem(problem)

    with patch(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        side_effect=_solve_side_effect,
    ):
        failing_inference = get_scores_row_inference(sample_turn, failing_player_id)
        other_inferences = [
            get_scores_row_inference(sample_turn, row.ownerid)
            for row in sample_turn.scores
            if row.ownerid != failing_player_id
        ]

    assert failing_inference["status"] == STATUS_SOLVER_ERROR
    assert len(other_inferences) == len(sample_turn.scores) - 1
    assert all("status" in inference for inference in other_inferences)


def _minimal_inference_problem(
    observation: InferenceObservation, catalog: ActionCatalog
) -> InferenceProblem:
    return InferenceProblem(
        observation=observation,
        aggregate_actions=catalog.aggregate_actions,
        ship_build_combos=catalog.ship_build_combos,
        policy_step_id=catalog.policy_step_id,
        policy_step_index=catalog.policy_step_index,
        probability_buckets_by_action_id=catalog.probability_buckets_by_action_id,
    )


def test_inference_result_payload_merges_catalog_diagnostics(sample_turn):
    catalog = ActionCatalog(
        aggregate_actions=(),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    observation = build_inference_observation(sample_turn.scores[0], sample_turn)
    problem = _minimal_inference_problem(observation, catalog)
    result = InferenceResult(
        status=STATUS_INVALID_PROBLEM,
        solutions=(),
        diagnostics={"reason": "empty catalog"},
    )
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    assert payload["status"] == STATUS_INVALID_PROBLEM
    assert payload["diagnostics"]["solver"]["reason"] == "empty catalog"
    assert payload["diagnostics"]["catalog_size"] == 0
    assert payload["diagnostics"]["constraints"]["playerId"] == sample_turn.scores[0].ownerid
    assert payload["diagnostics"]["actionCatalog"]["catalogSize"] == 0


def test_inference_result_payload_serializes_solutions(sample_turn):
    catalog = ActionCatalog(
        aggregate_actions=(),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    observation = build_inference_observation(sample_turn.scores[0], sample_turn)
    problem = _minimal_inference_problem(observation, catalog)
    result = InferenceResult(
        status=STATUS_EXACT,
        solutions=(
            InferenceSolution(
                objective_value=42,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense",
                        label="Planet defense post",
                        count=2,
                    ),
                ),
            ),
        ),
        diagnostics={"solution_count": 1},
    )
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    assert payload["solutionCount"] == 1
    assert payload["solutions"][0]["objectiveValue"] == 42
    assert payload["solutions"][0]["actions"][0]["actionId"] == "planet_defense"


def test_inference_result_payload_includes_military_score_arithmetic(sample_turn):
    defense_action = CandidateAction(
        id="planet_defense",
        label="Planet defense post",
        score_delta_2x=22,
        lower_bound=0,
        upper_bound=10,
    )
    catalog = ActionCatalog(
        aggregate_actions=(defense_action,),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    score = sample_turn.scores[0]
    observation = InferenceObservation(
        player_id=score.ownerid,
        turn=12,
        military_delta_2x=44,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=2,
        is_after_ship_limit=False,
    )
    problem = _minimal_inference_problem(observation, catalog)
    result = InferenceResult(
        status=STATUS_EXACT,
        solutions=(
            InferenceSolution(
                objective_value=99,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense",
                        label="Planet defense post",
                        count=2,
                    ),
                ),
            ),
        ),
        diagnostics={},
    )
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    arithmetic = payload["solutions"][0]["militaryScoreArithmetic"]
    assert arithmetic["observedMilitaryChange"] == 22
    assert arithmetic["observedMilitaryDelta2x"] == 44
    assert arithmetic["explainedMilitaryChange"] == 22
    assert arithmetic["explainedMilitaryDelta2x"] == 44
    assert arithmetic["matchesObserved"] is True
    line_item = arithmetic["lineItems"][0]
    assert line_item["count"] == 2
    assert line_item["scoreDelta2xPerUnit"] == 22
    assert line_item["militaryChangePerUnit"] == 11
    assert line_item["militaryChangeSubtotal"] == 22


def test_solution_military_score_arithmetic_flags_mismatch():
    observation = InferenceObservation(
        player_id=1,
        turn=3,
        military_delta_2x=100,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
    )
    action = CandidateAction(
        id="starbase_fighter",
        label="Starbase fighter",
        score_delta_2x=125,
    )
    solution = InferenceSolution(
        objective_value=1,
        actions=(
            InferenceSolutionAction(
                action_id="starbase_fighter",
                label="Starbase fighter",
                count=1,
            ),
        ),
    )
    arithmetic = solution_military_score_arithmetic_payload(
        solution,
        observation,
        {action.id: action},
    )
    assert arithmetic["matchesObserved"] is False
    assert arithmetic["explainedMilitaryChange"] == 62


def test_constraints_payload_exposes_requested_pp_as_diagnostic_only():
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=0,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=54,
        starbases_owned=3,
        is_after_ship_limit=False,
    )
    constraints = observation_to_constraints_payload(observation)

    assert constraints["requestedPriorityPointDelta"] == 54
    assert constraints["priorityPointConstraintEnforced"] is False
    assert "not a hard solver constraint" in str(constraints["priorityPointConstraintNote"])
    assert "priorityPointDelta" not in constraints
    applied = constraints["appliedEqualities"]
    assert not any("priorityPointDelta" in equality for equality in applied)


def test_row_inference_includes_structured_solver_diagnostics(sample_turn):
    player_id = sample_turn.scores[0].ownerid
    inference = get_scores_row_inference(sample_turn, player_id)
    diagnostics = inference["diagnostics"]
    assert diagnostics["turn"] == sample_turn.settings.turn
    assert "constraints" in diagnostics
    assert "actionCatalog" in diagnostics
    assert "solver" in diagnostics
    assert isinstance(diagnostics["constraints"]["appliedEqualities"], list)
    assert diagnostics["constraints"]["priorityPointConstraintEnforced"] is False
    assert "priorityPointConstraintNote" in diagnostics["constraints"]
    assert isinstance(diagnostics["actionCatalog"]["actions"], list)
    assert "meta" in diagnostics["actionCatalog"]
    assert "shipBuildCombos" in diagnostics["actionCatalog"]
    assert "rankingHeuristics" in diagnostics
    assert "diversityCapsApplied" in diagnostics["constraints"]
    assert "rankingHeuristics" not in diagnostics["solver"]
    assert "diversityCapsApplied" not in diagnostics["solver"]


def test_build_inference_solver_diagnostics_passes_through_solver_owned_keys():
    from api.analytics.military_score_inference.analytic import build_inference_solver_diagnostics

    solver_owned = {
        "status": "exact",
        "rankingHeuristics": {"partialWeaponSlotPenaltyPerLine": -25},
        "diversityCapsApplied": [{"superclass": "torpedo_loads", "cap": 2}],
        "solver_status": "OPTIMAL",
    }
    payload = build_inference_solver_diagnostics(
        turn=5,
        solver=solver_owned,
    )

    assert payload["rankingHeuristics"] == {"partialWeaponSlotPenaltyPerLine": -25}
    assert payload["solver"] == {"status": "exact", "solver_status": "OPTIMAL"}


def test_inference_diagnostics_include_policy_ladder_fields(sample_turn):
    score = sample_turn.scores[0]
    inference = infer_military_score_build(score, sample_turn)
    diagnostics = inference["diagnostics"]
    assert "policy_step_id" in diagnostics
    assert "policy_step_index" in diagnostics
    assert "ship_build_combo_count" in diagnostics
    assert "policy_steps_attempted" in diagnostics
    assert isinstance(diagnostics["policy_steps_attempted"], list)
    assert diagnostics["policy_steps_attempted"]
    assert "policy_step_attempts" in diagnostics


def test_registry_still_exposes_only_scores_analytic(sample_turn):
    from api.analytics.registry import TURN_ANALYTIC_CATALOG
    from api.analytics.registry import TURN_ANALYTICS

    assert set(TURN_ANALYTICS) == {entry.id for entry in TURN_ANALYTIC_CATALOG}
    data = get_turn_analytic(
        "scores",
        sample_turn,
        TurnAnalyticsOptions(),
    )
    assert data["analyticId"] == "scores"
    assert "inference" not in data["rows"][0]
