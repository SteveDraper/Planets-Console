"""Drop ship fittings that cannot land in the military window.

The catalog already stores each fitting's military score. This pass keeps a
warship fitting only when some positive count of it can meet the window, using
the widest military range of the free aggregates and the cheapest and costliest
other warship scores. That overstates what the solver can actually reach, so a
fitting that is kept may still be infeasible. A fitting that is dropped cannot
be selected.

Non-warship fittings, fittings with a forced lower bound, and fittings whose
count is already fixed at zero stay in the model. The ranking scale is not
decided here; the model build reads the max combo weight before this filter.
"""

from __future__ import annotations

from collections.abc import Sequence

from api.analytics.military_score_inference.military_score_window import military_window_bounds
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceProblem,
    ShipBuildCombo,
    action_military_range_2x,
    candidate_military_subtotal_bounds_2x,
)


def reachable_ship_fittings(
    problem: InferenceProblem,
    combos: Sequence[ShipBuildCombo],
) -> tuple[ShipBuildCombo, ...]:
    """Return the fittings the CP-SAT model should still offer."""
    if not _counts_are_single_ships(problem, combos):
        return tuple(combos)

    bounds = military_window_bounds(
        problem.military_score_window,
        rhs=problem.observation.military_delta_2x,
        slack=problem.observation.military_partition_slack_2x,
    )
    if bounds.equal is not None:
        lower: int | None = bounds.equal
        upper: int | None = bounds.equal
    else:
        lower = bounds.lower
        upper = bounds.upper
    if lower is None and upper is None:
        return tuple(combos)

    aggregate_low, aggregate_high = _free_aggregate_military_range(problem.aggregate_actions)
    unit_low, unit_high, warship_capacity = _warship_unit_scores(problem.aggregate_actions, combos)
    freighter_low, freighter_high = _freighter_military(problem, combos)
    warships_required = problem.observation.warship_delta

    kept: list[ShipBuildCombo] = []
    for combo in combos:
        if not _is_optional_warship(combo):
            kept.append(combo)
            continue
        if _warship_can_meet_window(
            combo,
            warships_required=warships_required,
            other_warship_capacity=warship_capacity - combo.upper_bound,
            unit_low=unit_low,
            unit_high=unit_high,
            aggregate_low=aggregate_low + freighter_low,
            aggregate_high=aggregate_high + freighter_high,
            lower=lower,
            upper=upper,
        ):
            kept.append(combo)
    return tuple(kept)


def _counts_are_single_ships(
    problem: InferenceProblem,
    combos: Sequence[ShipBuildCombo],
) -> bool:
    """The per-warship bound assumes each warship count step is one ship.

    Freighter gains and losses contribute no military score, so their deltas
    do not decide whether a warship fitting can meet the window.
    """
    for combo in combos:
        if combo.warship_delta not in (0, 1):
            return False
    for action in problem.aggregate_actions:
        if action.warship_delta not in (0, 1):
            return False
    return True


def _is_optional_warship(combo: ShipBuildCombo) -> bool:
    return combo.warship_delta == 1 and combo.lower_bound == 0 and combo.upper_bound > 0


def _warship_can_meet_window(
    combo: ShipBuildCombo,
    *,
    warships_required: int,
    other_warship_capacity: int,
    unit_low: int,
    unit_high: int,
    aggregate_low: int,
    aggregate_high: int,
    lower: int | None,
    upper: int | None,
) -> bool:
    max_count = min(combo.upper_bound, warships_required)
    for count in range(1, max_count + 1):
        remaining = warships_required - count
        if remaining > other_warship_capacity:
            continue
        low = combo.score_delta_2x * count + unit_low * remaining + aggregate_low
        high = combo.score_delta_2x * count + unit_high * remaining + aggregate_high
        if lower is not None and high < lower:
            continue
        if upper is not None and low > upper:
            continue
        return True
    return False


def _free_aggregate_military_range(
    actions: Sequence[CandidateAction],
) -> tuple[int, int]:
    low = 0
    high = 0
    for action in actions:
        if action.warship_delta != 0 or action.freighter_delta != 0:
            continue
        action_low, action_high = action_military_range_2x(action)
        low += action_low
        high += action_high
    return low, high


def _warship_unit_scores(
    actions: Sequence[CandidateAction],
    combos: Sequence[ShipBuildCombo],
) -> tuple[int, int, int]:
    lows: list[int] = []
    highs: list[int] = []
    capacity = 0
    for combo in combos:
        if combo.warship_delta != 1 or combo.upper_bound <= 0:
            continue
        lows.append(combo.score_delta_2x)
        highs.append(combo.score_delta_2x)
        capacity += combo.upper_bound
    for action in actions:
        if action.warship_delta != 1 or action.upper_bound <= 0:
            continue
        action_low, action_high = candidate_military_subtotal_bounds_2x(action, 1)
        lows.append(action_low)
        highs.append(action_high)
        capacity += action.upper_bound
    if not lows:
        return 0, 0, capacity
    return min(lows), max(highs), capacity


def _freighter_military(
    problem: InferenceProblem,
    combos: Sequence[ShipBuildCombo],
) -> tuple[int, int]:
    required = problem.observation.freighter_delta
    if required <= 0:
        return 0, 0
    lows: list[int] = []
    highs: list[int] = []
    for combo in combos:
        if combo.freighter_delta != 1 or combo.warship_delta != 0 or combo.upper_bound <= 0:
            continue
        lows.append(combo.score_delta_2x)
        highs.append(combo.score_delta_2x)
    for action in problem.aggregate_actions:
        if action.freighter_delta != 1 or action.warship_delta != 0 or action.upper_bound <= 0:
            continue
        action_low, action_high = candidate_military_subtotal_bounds_2x(action, 1)
        lows.append(action_low)
        highs.append(action_high)
    if not lows:
        return 0, 0
    return min(lows) * required, max(highs) * required
