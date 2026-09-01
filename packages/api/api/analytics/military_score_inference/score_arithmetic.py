"""Per-solution military score arithmetic for inference API payloads."""

from dataclasses import dataclass

from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceSolution,
    ShipBuildCombo,
    candidate_action_has_military_interval,
    candidate_military_subtotal_bounds_2x,
)


@dataclass
class _Contribution:
    line_id_key: str
    line_id: str
    label: str
    count: int
    catalog_lo: int
    catalog_hi: int
    is_interval: bool
    tight_lo: int = 0
    tight_hi: int = 0
    assigned: int = 0


def solution_military_score_arithmetic_payload(
    solution: InferenceSolution,
    observation: InferenceObservation,
    actions_by_id: dict[str, CandidateAction],
    combos_by_id: dict[str, ShipBuildCombo] | None = None,
) -> dict[str, object]:
    """Explain how solution action counts sum to the observed military score delta.

    Catalog envelopes on interval actions stay wide for search. Emitted line items
    intersect those envelopes with leftover after the other elements of this
    solution so the row is self-consistent and maximally tight.
    """
    combo_lookup = combos_by_id or {}
    contributions = _contributions_for_solution(solution, actions_by_id, combo_lookup)
    _tighten_interval_contributions(contributions, observation)
    _assign_interval_contributions(contributions, observation)

    line_items = [_line_item_payload(item) for item in contributions]
    explained_military_delta_2x = sum(item.assigned for item in contributions)
    observed_military_delta_2x = observation.military_delta_2x
    slack = observation.military_partition_slack_2x
    return {
        "observedMilitaryChange": observed_military_delta_2x // 2,
        "observedMilitaryDelta2x": observed_military_delta_2x,
        "explainedMilitaryChange": explained_military_delta_2x // 2,
        "explainedMilitaryDelta2x": explained_military_delta_2x,
        "militaryPartitionSlack2x": slack,
        "matchesObserved": abs(explained_military_delta_2x - observed_military_delta_2x) <= slack,
        "lineItems": line_items,
    }


def _contributions_for_solution(
    solution: InferenceSolution,
    actions_by_id: dict[str, CandidateAction],
    combo_lookup: dict[str, ShipBuildCombo],
) -> list[_Contribution]:
    contributions: list[_Contribution] = []
    for solution_action in solution.actions:
        if solution_action.count == 0:
            continue
        catalog_action = actions_by_id.get(solution_action.action_id)
        if catalog_action is None:
            contributions.append(
                _Contribution(
                    line_id_key="actionId",
                    line_id=solution_action.action_id,
                    label=solution_action.label,
                    count=solution_action.count,
                    catalog_lo=0,
                    catalog_hi=0,
                    is_interval=False,
                )
            )
            continue
        catalog_lo, catalog_hi = candidate_military_subtotal_bounds_2x(
            catalog_action, solution_action.count
        )
        contributions.append(
            _Contribution(
                line_id_key="actionId",
                line_id=solution_action.action_id,
                label=solution_action.label,
                count=solution_action.count,
                catalog_lo=catalog_lo,
                catalog_hi=catalog_hi,
                is_interval=candidate_action_has_military_interval(catalog_action),
            )
        )
    for ship_build in solution.ship_builds:
        if ship_build.count == 0:
            continue
        catalog_combo = combo_lookup.get(ship_build.combo_id)
        point = catalog_combo.score_delta_2x * ship_build.count if catalog_combo is not None else 0
        contributions.append(
            _Contribution(
                line_id_key="comboId",
                line_id=ship_build.combo_id,
                label=ship_build.label,
                count=ship_build.count,
                catalog_lo=point,
                catalog_hi=point,
                is_interval=False,
            )
        )
    return contributions


def _tighten_interval_contributions(
    contributions: list[_Contribution],
    observation: InferenceObservation,
) -> None:
    for item in contributions:
        item.tight_lo = item.catalog_lo
        item.tight_hi = item.catalog_hi
    slack = observation.military_partition_slack_2x
    observed = observation.military_delta_2x
    changed = True
    while changed:
        changed = False
        for index, item in enumerate(contributions):
            if not item.is_interval:
                continue
            other_min = 0
            other_max = 0
            for other_index, other in enumerate(contributions):
                if other_index == index:
                    continue
                other_min += other.tight_lo
                other_max += other.tight_hi
            need_lo = observed - slack - other_max
            need_hi = observed + slack - other_min
            new_lo = max(item.tight_lo, need_lo)
            new_hi = min(item.tight_hi, need_hi)
            if new_lo > new_hi:
                continue
            if new_lo != item.tight_lo or new_hi != item.tight_hi:
                item.tight_lo = new_lo
                item.tight_hi = new_hi
                changed = True


def _assign_interval_contributions(
    contributions: list[_Contribution],
    observation: InferenceObservation,
) -> None:
    slack = observation.military_partition_slack_2x
    observed = observation.military_delta_2x
    sum_lo = sum(item.tight_lo for item in contributions)
    sum_hi = sum(item.tight_hi for item in contributions)
    feasible_lo = max(sum_lo, observed - slack)
    feasible_hi = min(sum_hi, observed + slack)
    if feasible_lo > feasible_hi:
        for item in contributions:
            item.assigned = item.catalog_lo
        return
    if observed < feasible_lo:
        target = feasible_lo
    elif observed > feasible_hi:
        target = feasible_hi
    else:
        target = observed
    for item in contributions:
        item.assigned = item.tight_lo
    remainder = target - sum(item.assigned for item in contributions)
    for item in contributions:
        if remainder <= 0:
            break
        if not item.is_interval:
            continue
        room = item.tight_hi - item.assigned
        take = min(room, remainder)
        item.assigned += take
        remainder -= take


def _line_item_payload(item: _Contribution) -> dict[str, object]:
    per_unit = item.assigned // item.count if item.count else 0
    payload: dict[str, object] = {
        item.line_id_key: item.line_id,
        "label": item.label,
        "count": item.count,
        "scoreDelta2xPerUnit": per_unit,
        "militaryChangePerUnit": per_unit // 2,
        "scoreDelta2xSubtotal": item.assigned,
        "militaryChangeSubtotal": item.assigned // 2,
    }
    if item.is_interval and item.tight_lo != item.tight_hi:
        payload["scoreDelta2xSubtotalMin"] = item.tight_lo
        payload["scoreDelta2xSubtotalMax"] = item.tight_hi
        payload["militaryChangeSubtotalMin"] = item.tight_lo // 2
        payload["militaryChangeSubtotalMax"] = item.tight_hi // 2
    return payload
