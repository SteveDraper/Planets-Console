"""Tier 1 constraint re-check and top-K ranking for inference corpus cases."""

from collections import Counter

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.models import CandidateAction, InferenceObservation

from tests.inference_corpus.ground_truth import GroundTruth

_EVIL_EMPIRE_FREE_STARBASE_FIGHTERS_ACTION_ID = "evil_empire_free_starbase_fighters"
_STARBASE_FIGHTERS_AGGREGATE_ACTION_ID = "starbase_fighters_added_total"


def normalize_ground_truth_multiset_for_comparison(multiset: GroundTruth) -> GroundTruth:
    """Fold solver-internal action ids into inventory-derived GT aggregates for ranking."""
    counter: Counter[str] = Counter(dict(multiset))
    ee_free_fighters = counter.pop(_EVIL_EMPIRE_FREE_STARBASE_FIGHTERS_ACTION_ID, 0)
    if ee_free_fighters:
        counter[_STARBASE_FIGHTERS_AGGREGATE_ACTION_ID] += ee_free_fighters
    return tuple(sorted((action_id, count) for action_id, count in counter.items() if count != 0))


def verify_top_solution_hard_equalities(
    *,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    inference_payload: dict[str, object],
) -> str | None:
    """Return an error message when the top solution violates hard equalities."""
    actions_by_id: dict[str, CandidateAction] = {
        action.id: action for action in catalog.aggregate_actions
    }
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}

    solutions = inference_payload.get("solutions")
    if not isinstance(solutions, list) or not solutions:
        return "no solutions to verify"

    top = solutions[0]
    if not isinstance(top, dict):
        return "top solution is not an object"

    action_entries = top.get("actions")
    if not isinstance(action_entries, list):
        return "top solution actions missing"

    ship_build_entries = top.get("shipBuilds")
    if ship_build_entries is None:
        ship_build_entries = []
    if not isinstance(ship_build_entries, list):
        return "top solution shipBuilds must be a list"

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

    for index, entry in enumerate(ship_build_entries):
        parsed = _parse_solution_ship_build_entry(index, entry)
        if isinstance(parsed, str):
            return parsed
        combo_id, count = parsed
        catalog_combo = combos_by_id.get(combo_id)
        if catalog_combo is None:
            return f"unknown combo id in top solution: {combo_id}"
        military_sum += catalog_combo.score_delta_2x * count
        warship_sum += catalog_combo.warship_delta * count
        freighter_sum += catalog_combo.freighter_delta * count

    if abs(military_sum - observation.military_delta_2x) > observation.military_partition_slack_2x:
        return (
            f"military delta mismatch: explained 2x={military_sum} "
            f"observed 2x={observation.military_delta_2x} "
            f"(slack 2x={observation.military_partition_slack_2x})"
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


def _parse_solution_ship_build_entry(
    index: int,
    entry: object,
) -> tuple[str, int] | str:
    if not isinstance(entry, dict):
        return f"top solution shipBuilds[{index}] must be an object, got {type(entry).__name__}"

    combo_id = entry.get("comboId")
    if not isinstance(combo_id, str) or not combo_id:
        return f"top solution shipBuilds[{index}].comboId must be a non-empty string"

    count = entry.get("count")
    if not isinstance(count, int):
        return f"top solution shipBuilds[{index}].count must be an integer"
    if count <= 0:
        return f"top solution shipBuilds[{index}].count must be positive, got {count}"

    return combo_id, count


def solution_to_ground_truth(solution: dict[str, object]) -> GroundTruth:
    """Normalize one wire solution into a sorted ground-truth multiset."""
    multiset: Counter[str] = Counter()

    action_entries = solution.get("actions")
    if isinstance(action_entries, list):
        for entry in action_entries:
            if not isinstance(entry, dict):
                continue
            action_id = entry.get("actionId")
            count = entry.get("count")
            if isinstance(action_id, str) and isinstance(count, int) and count > 0:
                multiset[action_id] += count

    ship_build_entries = solution.get("shipBuilds")
    if isinstance(ship_build_entries, list):
        for entry in ship_build_entries:
            if not isinstance(entry, dict):
                continue
            combo_id = entry.get("comboId")
            count = entry.get("count")
            if isinstance(combo_id, str) and isinstance(count, int) and count > 0:
                multiset[combo_id] += count

    return normalize_ground_truth_multiset_for_comparison(
        tuple(sorted((action_id, count) for action_id, count in multiset.items()))
    )


def check_ground_truth_in_top_k(
    ground_truth: GroundTruth,
    solutions: list[object],
    *,
    k: int,
) -> tuple[bool, int | None]:
    """Return whether GT appears in the first K solutions and its 1-based full-list rank."""
    normalized_ground_truth = normalize_ground_truth_multiset_for_comparison(ground_truth)
    ground_truth_rank: int | None = None
    for index, solution in enumerate(solutions):
        if not isinstance(solution, dict):
            continue
        if solution_to_ground_truth(solution) == normalized_ground_truth:
            ground_truth_rank = index + 1
            break

    if ground_truth_rank is None:
        return False, None
    return ground_truth_rank <= k, ground_truth_rank
