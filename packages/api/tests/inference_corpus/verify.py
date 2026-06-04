"""Tier 1 constraint re-check for inference corpus cases."""

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.models import CandidateAction, InferenceObservation


def verify_top_solution_hard_equalities(
    *,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    inference_payload: dict[str, object],
) -> str | None:
    """Return an error message when the top solution violates hard equalities."""
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
    for index, entry in enumerate(action_entries):
        parsed = _parse_solution_action_entry(index, entry)
        if isinstance(parsed, str):
            return parsed
        action_id, count = parsed
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


def _parse_solution_action_entry(
    index: int,
    entry: object,
) -> tuple[str, int] | str:
    """Return (actionId, count) or an error message for a malformed serialized action."""
    if not isinstance(entry, dict):
        return f"top solution actions[{index}] must be an object, got {type(entry).__name__}"

    action_id = entry.get("actionId")
    if not isinstance(action_id, str) or not action_id:
        return f"top solution actions[{index}].actionId must be a non-empty string"

    count = entry.get("count")
    if not isinstance(count, int):
        return f"top solution actions[{index}].count must be an integer"
    if count <= 0:
        return f"top solution actions[{index}].count must be positive, got {count}"

    return action_id, count
