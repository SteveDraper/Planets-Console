"""Military score build inference (internal to the scores analytic)."""

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
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
)

__all__ = [
    "LOADED_SHIP_FIGHTER_SCORE_DELTA_2X",
    "PLANET_DEFENSE_POST_SCORE_DELTA_2X",
    "STARBASE_DEFENSE_POST_SCORE_DELTA_2X",
    "STARBASE_FIGHTER_SCORE_DELTA_2X",
    "STATUS_EXACT",
    "STATUS_INVALID_PROBLEM",
    "STATUS_NO_EXACT_SOLUTION",
    "STATUS_TIME_LIMITED",
    "CandidateAction",
    "InferenceObservation",
    "InferenceProblem",
    "InferenceResult",
    "InferenceSolution",
    "InferenceSolutionAction",
    "ProbabilityBucket",
    "construction_value",
    "loaded_ship_fighter_score_delta_2x",
    "loaded_ship_torpedo_score_delta_2x",
    "planet_defense_post_score_delta_2x",
    "ship_construction_score_delta_2x",
    "solve_inference_problem",
    "starbase_defense_post_score_delta_2x",
    "starbase_fighter_score_delta_2x",
]
