"""Tier 1 constraint re-check for inference corpus cases."""

from api.analytics.military_score_inference.actions import build_action_catalog_from_turn
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.models import CandidateAction
from api.models.game import TurnInfo
from api.models.player import Score


def verify_top_solution_hard_equalities(
    *,
    score: Score,
    turn: TurnInfo,
    inference_payload: dict[str, object],
) -> str | None:
    """Return an error message when the top solution violates hard equalities."""
    observation = build_inference_observation(score, turn)
    catalog = build_action_catalog_from_turn(observation, turn)
    actions_by_id: dict[str, CandidateAction] = {action.id: action for action in catalog.actions}

    solutions = inference_payload.get("solutions")
    if not isinstance(solutions, list) or not solutions:
        return "no solutions to verify"

    top = solutions[0]
    if not isinstance(top, dict):
        return "top solution is not an object"

    action_entries = top.get("actions")
    if not isinstance(action_entries, list):
        return "top solution actions missing"

    military_sum = 0
    warship_sum = 0
    freighter_sum = 0
    for entry in action_entries:
        if not isinstance(entry, dict):
            continue
        action_id = entry.get("actionId")
        count = entry.get("count")
        if not isinstance(action_id, str) or not isinstance(count, int) or count == 0:
            continue
        catalog_action = actions_by_id.get(action_id)
        if catalog_action is None:
            return f"unknown action id in top solution: {action_id}"
        military_sum += catalog_action.score_delta_2x * count
        warship_sum += catalog_action.warship_delta * count
        freighter_sum += catalog_action.freighter_delta * count

    if military_sum != observation.military_delta_2x:
        return (
            f"military delta mismatch: explained 2x={military_sum} "
            f"observed 2x={observation.military_delta_2x}"
        )
    if warship_sum != observation.warship_delta:
        return (
            f"warship delta mismatch: explained={warship_sum} observed={observation.warship_delta}"
        )
    if freighter_sum != observation.freighter_delta:
        return (
            f"freighter delta mismatch: explained={freighter_sum} "
            f"observed={observation.freighter_delta}"
        )
    return None
