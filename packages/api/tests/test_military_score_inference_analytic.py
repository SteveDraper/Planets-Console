"""Tests for military score inference integration with the scores analytic."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import (
    STATUS_NO_PRIOR_TURN,
    STATUS_SOLVER_ERROR,
    build_inference_observation,
    infer_military_score_build,
    inference_result_to_api_payload,
    is_after_ship_limit,
    prior_turn_score_data_available,
)
from api.analytics.military_score_inference.models import (
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    solve_inference_problem,
)
from api.analytics.scores import get_scores_table
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_turn():
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        return turn_info_from_json(json.load(handle))


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


def test_scores_output_includes_inference_when_enabled(sample_turn):
    data = get_scores_table(
        sample_turn,
        TurnAnalyticsOptions(include_military_score_inference=True),
    )
    inference = data["rows"][0]["inference"]
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


def test_enabled_first_turn_attaches_row_level_diagnostic(first_turn):
    data = get_scores_table(
        first_turn,
        TurnAnalyticsOptions(include_military_score_inference=True),
    )
    for row in data["rows"]:
        assert row["inference"]["status"] == STATUS_NO_PRIOR_TURN


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
        "api.analytics.military_score_inference.analytic.solve_inference_problem",
        side_effect=_solve_side_effect,
    ):
        data = get_scores_table(
            sample_turn,
            TurnAnalyticsOptions(include_military_score_inference=True),
        )

    failed_rows = [row for row in data["rows"] if row["playerId"] == failing_player_id]
    other_rows = [row for row in data["rows"] if row["playerId"] != failing_player_id]
    assert len(data["rows"]) == len(sample_turn.scores)
    assert failed_rows[0]["inference"]["status"] == STATUS_SOLVER_ERROR
    assert all("inference" in row for row in other_rows)


def test_inference_result_payload_merges_catalog_diagnostics(sample_turn):
    catalog = ActionCatalog(actions=(), probability_buckets_by_action_id={})
    observation = build_inference_observation(sample_turn.scores[0], sample_turn)
    result = InferenceResult(
        status=STATUS_INVALID_PROBLEM,
        solutions=(),
        diagnostics={"reason": "empty catalog"},
    )
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn)
    assert payload["status"] == STATUS_INVALID_PROBLEM
    assert payload["diagnostics"]["solver"]["reason"] == "empty catalog"
    assert payload["diagnostics"]["catalog_size"] == 0
    assert payload["diagnostics"]["constraints"]["playerId"] == sample_turn.scores[0].ownerid
    assert payload["diagnostics"]["actionCatalog"]["catalogSize"] == 0


def test_inference_result_payload_serializes_solutions(sample_turn):
    catalog = ActionCatalog(actions=(), probability_buckets_by_action_id={})
    observation = build_inference_observation(sample_turn.scores[0], sample_turn)
    result = InferenceResult(
        status=STATUS_EXACT,
        solutions=(
            InferenceSolution(
                objective_value=42,
                actions=(
                    InferenceSolutionAction(
                        action_id="build_24_empty",
                        label="Build Serpent Class Escort (empty)",
                        count=1,
                    ),
                ),
            ),
        ),
        diagnostics={"solution_count": 1},
    )
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn)
    assert payload["solutionCount"] == 1
    assert payload["solutions"][0]["objectiveValue"] == 42
    assert payload["solutions"][0]["actions"][0]["actionId"] == "build_24_empty"


def test_enabled_output_includes_structured_solver_diagnostics(sample_turn):
    data = get_scores_table(
        sample_turn,
        TurnAnalyticsOptions(include_military_score_inference=True),
    )
    inference = data["rows"][0]["inference"]
    diagnostics = inference["diagnostics"]
    assert diagnostics["turn"] == sample_turn.settings.turn
    assert "constraints" in diagnostics
    assert "actionCatalog" in diagnostics
    assert "solver" in diagnostics
    assert isinstance(diagnostics["constraints"]["appliedEqualities"], list)
    assert isinstance(diagnostics["actionCatalog"]["actions"], list)
    assert "meta" in diagnostics["actionCatalog"]
    assert "shipBuildActions" in diagnostics["actionCatalog"]


def test_registry_still_exposes_only_scores_analytic(sample_turn):
    from api.analytics.registry import TURN_ANALYTICS

    assert set(TURN_ANALYTICS) == {"base-map", "connections", "scores", "stellar-cartography"}
    data = get_turn_analytic(
        "scores",
        sample_turn,
        TurnAnalyticsOptions(include_military_score_inference=True),
    )
    assert data["analyticId"] == "scores"
    assert "inference" in data["rows"][0]
