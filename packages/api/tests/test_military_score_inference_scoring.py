"""Tests for military score inference contracts and scaled score arithmetic."""

from dataclasses import FrozenInstanceError

import pytest
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
    ProbabilityBucket,
)
from api.analytics.military_score_inference.scoring import (
    LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
    PLANET_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_FIGHTER_SCORE_DELTA_2X,
    construction_value,
    loaded_ship_fighter_score_delta_2x,
    loaded_ship_torpedo_score_delta_2x,
    planet_defense_post_score_delta_2x,
    ship_construction_score_delta_2x,
    starbase_defense_post_score_delta_2x,
    starbase_fighter_score_delta_2x,
)


def test_construction_value_uses_megacredits_and_minerals():
    assert construction_value(100, 20) == 200


def test_ship_construction_score_delta_2x_scales_construction_value():
    assert ship_construction_score_delta_2x(100, 20) == 400


def test_loaded_ship_fighter_score_delta_2x():
    assert loaded_ship_fighter_score_delta_2x() == 250
    assert loaded_ship_fighter_score_delta_2x(3) == 750
    assert LOADED_SHIP_FIGHTER_SCORE_DELTA_2X == 250


def test_loaded_ship_torpedo_score_delta_2x():
    assert loaded_ship_torpedo_score_delta_2x(1) == 2
    assert loaded_ship_torpedo_score_delta_2x(5, count=4) == 40


def test_starbase_fighter_score_delta_2x():
    assert starbase_fighter_score_delta_2x() == 125
    assert starbase_fighter_score_delta_2x(2) == 250
    assert STARBASE_FIGHTER_SCORE_DELTA_2X == 125


def test_starbase_defense_post_score_delta_2x():
    assert starbase_defense_post_score_delta_2x() == 15
    assert starbase_defense_post_score_delta_2x(10) == 150
    assert STARBASE_DEFENSE_POST_SCORE_DELTA_2X == 15


def test_planet_defense_post_score_delta_2x():
    assert planet_defense_post_score_delta_2x() == 11
    assert planet_defense_post_score_delta_2x(100) == 1100
    assert PLANET_DEFENSE_POST_SCORE_DELTA_2X == 11


def test_inference_dataclasses_are_frozen():
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=400,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=3,
        is_after_ship_limit=False,
    )
    with pytest.raises(FrozenInstanceError):
        observation.turn = 6


def test_inference_problem_carries_actions_and_buckets():
    observation = InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=11,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
    )
    action = CandidateAction(
        id="planet_defense_posts",
        label="Planet defense posts",
        score_delta_2x=PLANET_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=100,
    )
    bucket = ProbabilityBucket(
        label="modest build-up",
        lower_count=0,
        upper_count=10,
        marginal_weight=100,
    )
    problem = InferenceProblem(
        observation=observation,
        actions=(action,),
        probability_buckets_by_action_id={action.id: (bucket,)},
    )
    result = InferenceResult(
        status="exact",
        solutions=(
            InferenceSolution(
                objective_value=100,
                actions=(
                    InferenceSolutionAction(
                        action_id=action.id,
                        label=action.label,
                        count=1,
                    ),
                ),
            ),
        ),
        diagnostics={"solver_status": "OPTIMAL"},
    )

    assert problem.actions[0].score_delta_2x == 11
    assert problem.probability_buckets_by_action_id[action.id][0].marginal_weight == 100
    assert result.solutions[0].actions[0].count == 1
