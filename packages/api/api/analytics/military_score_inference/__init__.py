"""Military score build inference (internal to the scores analytic)."""

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    ActionCatalogConfig,
    build_action_catalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ProbabilityBucket,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.scoring import (
    LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
    LOADED_TORPEDO_AMMO_MINERALS,
    PLANET_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_FIGHTER_SCORE_DELTA_2X,
    loaded_ship_fighter_score_delta_2x,
    loaded_ship_torpedo_score_delta_2x,
    planet_defense_post_score_delta_2x,
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
from api.concepts.ship_build_military import (
    construction_value,
    ship_construction_score_delta_2x,
)

__all__ = [
    "LOADED_SHIP_FIGHTER_SCORE_DELTA_2X",
    "LOADED_TORPEDO_AMMO_MINERALS",
    "PLANET_DEFENSE_POST_SCORE_DELTA_2X",
    "STARBASE_DEFENSE_POST_SCORE_DELTA_2X",
    "STARBASE_FIGHTER_SCORE_DELTA_2X",
    "STATUS_EXACT",
    "STATUS_INVALID_PROBLEM",
    "STATUS_NO_EXACT_SOLUTION",
    "STATUS_TIME_LIMITED",
    "ActionCatalog",
    "ActionCatalogConfig",
    "CandidateAction",
    "InferenceObservation",
    "InferenceProblem",
    "InferenceResult",
    "InferenceSolution",
    "InferenceSolutionAction",
    "InferenceSolutionShipBuild",
    "ProbabilityBucket",
    "ShipBuildCombo",
    "build_action_catalog",
    "build_action_catalog_from_turn",
    "build_inference_problem",
    "construction_value",
    "loaded_ship_fighter_score_delta_2x",
    "loaded_ship_torpedo_score_delta_2x",
    "planet_defense_post_score_delta_2x",
    "ship_construction_score_delta_2x",
    "solve_inference_problem",
    "starbase_defense_post_score_delta_2x",
    "starbase_fighter_score_delta_2x",
]
