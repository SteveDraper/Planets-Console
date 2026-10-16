"""Reject seed-neighborhood solves whose pinned ships cannot meet the observation."""

from __future__ import annotations

from itertools import product

from api.analytics.military_score_inference.catalog_model import CatalogMergePlan, MergeGroup
from api.analytics.military_score_inference.military_score_window import (
    ExactMilitaryScoreWindow,
    MilitaryWindowBounds,
    military_window_bounds,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    ShipBuildCombo,
    candidate_military_subtotal_bounds_2x,
)

# Neighborhood domains are tiny (a pin, or pin +/- 1). Past this many combinations
# the screen uses an independent range box instead of enumerating counts.
_MAX_PINNED_ASSIGNMENTS = 256


def negative_band_upper_bound_is_unreachable(
    observation: InferenceObservation,
    aggregate_actions: tuple[CandidateAction, ...],
    ship_build_combos: tuple[ShipBuildCombo, ...] = (),
) -> bool:
    """True when a negative band ceiling cannot be reached by a legal assignment.

    The ceiling is the observed military score. Freighter departures contribute
    no military score, so only a warship decrease, or an action that scores
    negative without changing the warship count, can reach it. A warship loss
    is not selectable when the warship count did not decrease and nothing in
    the catalog builds one back.
    """
    if observation.military_delta_2x >= 0:
        return False
    warship_supply = _positive_class_capacity(
        aggregate_actions,
        ship_build_combos,
        "warship_delta",
    )
    for action in aggregate_actions:
        if _negative_action_can_be_selected(
            action,
            observation,
            warship_supply=warship_supply,
        ):
            return False
    for combo in ship_build_combos:
        if combo.score_delta_2x >= 0 or combo.upper_bound <= 0:
            continue
        if _warship_decrease_is_admissible(
            combo.warship_delta,
            observation,
            warship_supply=warship_supply,
        ):
            return False
    return True


def _positive_class_capacity(
    aggregate_actions: tuple[CandidateAction, ...],
    ship_build_combos: tuple[ShipBuildCombo, ...],
    attribute: str,
) -> int:
    total = 0
    for action in aggregate_actions:
        delta = getattr(action, attribute)
        if delta > 0 and action.upper_bound > 0:
            total += delta * action.upper_bound
    for combo in ship_build_combos:
        delta = getattr(combo, attribute)
        if delta > 0 and combo.upper_bound > 0:
            total += delta * combo.upper_bound
    return total


def _negative_action_can_be_selected(
    action: CandidateAction,
    observation: InferenceObservation,
    *,
    warship_supply: int,
) -> bool:
    if action.upper_bound <= 0:
        return False
    military_low, _military_high = candidate_military_subtotal_bounds_2x(action, 1)
    if military_low >= 0:
        return False
    return _warship_decrease_is_admissible(
        action.warship_delta,
        observation,
        warship_supply=warship_supply,
    )


def _warship_decrease_is_admissible(
    warship_delta: int,
    observation: InferenceObservation,
    *,
    warship_supply: int,
) -> bool:
    if warship_delta < 0 and observation.warship_delta >= 0 and warship_supply < -warship_delta:
        return False
    return True


def pinned_counts_cannot_explain(
    plan: CatalogMergePlan,
    observation: InferenceObservation,
    aggregate_actions: tuple[CandidateAction, ...],
    fixed_combo_counts: dict[str, int],
    neighborhood: int,
) -> bool:
    """True when every pinned count assignment misses the exact military window.

    Seed neighborhoods solve that window with every non-seed combo forced to zero.
    Aggregate actions stay free, so the check uses their count ranges. A pass that
    might still be feasible is left to the solver.
    """
    if not fixed_combo_counts:
        return False

    open_domains: list[tuple[MergeGroup, int, int]] = []
    seen_groups: set[int] = set()
    for combo_id in fixed_combo_counts:
        index = plan.member_group_index.get(combo_id)
        if index is None or index in seen_groups:
            continue
        seen_groups.add(index)
        group = plan.groups[index]
        lower_bound, upper_bound = plan.merged_count_bounds(
            group,
            fixed_combo_counts,
            neighborhood,
        )
        if lower_bound > upper_bound:
            return True
        if lower_bound == 0 and upper_bound == 0:
            continue
        open_domains.append((group, lower_bound, upper_bound))

    aggregate_warships = _summed_linear_range(aggregate_actions, "warship_delta")
    aggregate_freighters = _summed_linear_range(aggregate_actions, "freighter_delta")
    aggregate_military = _summed_military_range(aggregate_actions)
    aggregate_min_slots = _summed_linear_range(aggregate_actions, "build_slot_usage")[0]
    window = military_window_bounds(
        ExactMilitaryScoreWindow(),
        rhs=observation.military_delta_2x,
        slack=observation.military_partition_slack_2x,
    )

    assignment_count = 1
    for _group, lower_bound, upper_bound in open_domains:
        assignment_count *= upper_bound - lower_bound + 1
        if assignment_count > _MAX_PINNED_ASSIGNMENTS:
            return _range_box_cannot_explain(
                open_domains,
                observation,
                window,
                aggregate_warships,
                aggregate_freighters,
                aggregate_military,
                aggregate_min_slots,
            )

    count_axes = [
        range(lower_bound, upper_bound + 1) for _group, lower_bound, upper_bound in open_domains
    ]
    for counts in product(*count_axes):
        ship_military = 0
        ship_warships = 0
        ship_freighters = 0
        ship_slots = 0
        for (group, _lower, _upper), count in zip(open_domains, counts, strict=True):
            prototype = group.prototype
            ship_military += prototype.score_delta_2x * count
            ship_warships += prototype.warship_delta * count
            ship_freighters += prototype.freighter_delta * count
            ship_slots += prototype.build_slot_usage * count
        if _assignment_can_explain(
            observation,
            window,
            ship_military=ship_military,
            ship_warships=ship_warships,
            ship_freighters=ship_freighters,
            ship_slots=ship_slots,
            aggregate_warships=aggregate_warships,
            aggregate_freighters=aggregate_freighters,
            aggregate_military=aggregate_military,
            aggregate_min_slots=aggregate_min_slots,
        ):
            return False
    return True


def _range_box_cannot_explain(
    open_domains: list[tuple[MergeGroup, int, int]],
    observation: InferenceObservation,
    window: MilitaryWindowBounds,
    aggregate_warships: tuple[int, int],
    aggregate_freighters: tuple[int, int],
    aggregate_military: tuple[int, int],
    aggregate_min_slots: int,
) -> bool:
    """Sound rejection from independent count ranges when the pin is too wide to list."""
    ship_military = _sum_scaled(open_domains, "score_delta_2x")
    ship_warships = _sum_scaled(open_domains, "warship_delta")
    ship_freighters = _sum_scaled(open_domains, "freighter_delta")
    ship_slots = _sum_scaled(open_domains, "build_slot_usage")
    if ship_slots[0] + aggregate_min_slots > observation.starbases_owned:
        return True
    if not _contains(
        (ship_warships[0] + aggregate_warships[0], ship_warships[1] + aggregate_warships[1]),
        observation.warship_delta,
    ):
        return True
    if not _contains(
        (
            ship_freighters[0] + aggregate_freighters[0],
            ship_freighters[1] + aggregate_freighters[1],
        ),
        observation.freighter_delta,
    ):
        return True
    total_lower = ship_military[0] + aggregate_military[0]
    total_upper = ship_military[1] + aggregate_military[1]
    if window.equal is not None:
        return not total_lower <= window.equal <= total_upper
    if window.lower is not None and total_upper < window.lower:
        return True
    if window.upper is not None and total_lower > window.upper:
        return True
    return False


def _sum_scaled(
    open_domains: list[tuple[MergeGroup, int, int]],
    attribute: str,
) -> tuple[int, int]:
    lower = 0
    upper = 0
    for group, count_lower, count_upper in open_domains:
        coefficient = getattr(group.prototype, attribute)
        scaled = _linear_range(coefficient, count_lower, count_upper)
        lower += scaled[0]
        upper += scaled[1]
    return lower, upper


def _assignment_can_explain(
    observation: InferenceObservation,
    window: MilitaryWindowBounds,
    *,
    ship_military: int,
    ship_warships: int,
    ship_freighters: int,
    ship_slots: int,
    aggregate_warships: tuple[int, int],
    aggregate_freighters: tuple[int, int],
    aggregate_military: tuple[int, int],
    aggregate_min_slots: int,
) -> bool:
    if ship_slots + aggregate_min_slots > observation.starbases_owned:
        return False
    if not _contains(aggregate_warships, observation.warship_delta - ship_warships):
        return False
    if not _contains(aggregate_freighters, observation.freighter_delta - ship_freighters):
        return False
    total_lower = ship_military + aggregate_military[0]
    total_upper = ship_military + aggregate_military[1]
    if window.equal is not None:
        return total_lower <= window.equal <= total_upper
    if window.lower is not None and total_upper < window.lower:
        return False
    if window.upper is not None and total_lower > window.upper:
        return False
    return True


def _contains(bounds: tuple[int, int], target: int) -> bool:
    return bounds[0] <= target <= bounds[1]


def _linear_range(coefficient: int, lower_bound: int, upper_bound: int) -> tuple[int, int]:
    low = coefficient * lower_bound
    high = coefficient * upper_bound
    if low <= high:
        return low, high
    return high, low


def _summed_linear_range(
    actions: tuple[CandidateAction, ...],
    attribute: str,
) -> tuple[int, int]:
    lower = 0
    upper = 0
    for action in actions:
        scaled = _linear_range(
            getattr(action, attribute),
            action.lower_bound,
            action.upper_bound,
        )
        lower += scaled[0]
        upper += scaled[1]
    return lower, upper


def _summed_military_range(actions: tuple[CandidateAction, ...]) -> tuple[int, int]:
    lower = 0
    upper = 0
    for action in actions:
        if action.lower_bound > action.upper_bound:
            continue
        endpoints: list[int] = []
        for count in (action.lower_bound, action.upper_bound):
            count_lower, count_upper = candidate_military_subtotal_bounds_2x(action, count)
            endpoints.append(count_lower)
            endpoints.append(count_upper)
        lower += min(endpoints)
        upper += max(endpoints)
    return lower, upper
