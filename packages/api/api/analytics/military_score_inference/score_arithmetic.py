"""Per-solution military score arithmetic for inference API payloads."""

from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceSolution,
    ShipBuildCombo,
)


def solution_military_score_arithmetic_payload(
    solution: InferenceSolution,
    observation: InferenceObservation,
    actions_by_id: dict[str, CandidateAction],
    combos_by_id: dict[str, ShipBuildCombo] | None = None,
) -> dict[str, object]:
    """Explain how solution action counts sum to the observed military score delta."""
    combo_lookup = combos_by_id or {}
    line_items: list[dict[str, object]] = []
    explained_military_delta_2x = 0
    for solution_action in solution.actions:
        if solution_action.count == 0:
            continue
        catalog_action = actions_by_id.get(solution_action.action_id)
        score_delta_2x_per_unit = catalog_action.score_delta_2x if catalog_action is not None else 0
        subtotal_score_delta_2x = score_delta_2x_per_unit * solution_action.count
        explained_military_delta_2x += subtotal_score_delta_2x
        military_change_per_unit = score_delta_2x_per_unit // 2
        line_items.append(
            {
                "actionId": solution_action.action_id,
                "label": solution_action.label,
                "count": solution_action.count,
                "scoreDelta2xPerUnit": score_delta_2x_per_unit,
                "militaryChangePerUnit": military_change_per_unit,
                "scoreDelta2xSubtotal": subtotal_score_delta_2x,
                "militaryChangeSubtotal": subtotal_score_delta_2x // 2,
            }
        )

    for ship_build in solution.ship_builds:
        if ship_build.count == 0:
            continue
        catalog_combo = combo_lookup.get(ship_build.combo_id)
        score_delta_2x_per_unit = catalog_combo.score_delta_2x if catalog_combo is not None else 0
        subtotal_score_delta_2x = score_delta_2x_per_unit * ship_build.count
        explained_military_delta_2x += subtotal_score_delta_2x
        military_change_per_unit = score_delta_2x_per_unit // 2
        line_items.append(
            {
                "comboId": ship_build.combo_id,
                "label": ship_build.label,
                "count": ship_build.count,
                "scoreDelta2xPerUnit": score_delta_2x_per_unit,
                "militaryChangePerUnit": military_change_per_unit,
                "scoreDelta2xSubtotal": subtotal_score_delta_2x,
                "militaryChangeSubtotal": subtotal_score_delta_2x // 2,
            }
        )

    observed_military_delta_2x = observation.military_delta_2x
    observed_military_change = observed_military_delta_2x // 2
    explained_military_change = explained_military_delta_2x // 2
    return {
        "observedMilitaryChange": observed_military_change,
        "observedMilitaryDelta2x": observed_military_delta_2x,
        "explainedMilitaryChange": explained_military_change,
        "explainedMilitaryDelta2x": explained_military_delta_2x,
        "matchesObserved": explained_military_delta_2x == observed_military_delta_2x,
        "lineItems": line_items,
    }
