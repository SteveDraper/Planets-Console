"""Ship-first family tag and stratified hold (design §3.11)."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import replace

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.aggregate_action_registry import is_torp_load_action_id
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceSolution,
    ShipBuildCombo,
    ShipFirstFamily,
)
from api.analytics.military_score_inference.ranked_solution_buffer import (
    SolutionSignature,
    solution_signature,
)
from api.analytics.military_score_inference.score_arithmetic import (
    catalog_explained_military_delta_2x,
)

SHIP_FIRST_FAMILY_HOLD_FLOOR = 3

__all__ = (
    "SHIP_FIRST_FAMILY_HOLD_FLOOR",
    "admit_ship_first_ranked_solution",
    "classify_ship_first_family",
    "non_torp_military_2x",
    "tag_ship_first_near_solution",
)


def _catalog_lookups(
    catalog: ActionCatalog,
) -> tuple[dict[str, CandidateAction], dict[str, ShipBuildCombo]]:
    return (
        {action.id: action for action in catalog.aggregate_actions},
        {combo.combo_id: combo for combo in catalog.ship_build_combos},
    )


def non_torp_military_2x(solution: InferenceSolution, catalog: ActionCatalog) -> int:
    """Point-score military 2x excluding ``ship_torps_loaded_*`` ammo loads."""
    actions_by_id, combos_by_id = _catalog_lookups(catalog)
    explained = 0
    for action in solution.actions:
        if is_torp_load_action_id(action.action_id):
            continue
        explained += actions_by_id[action.action_id].score_delta_2x * action.count
    for ship_build in solution.ship_builds:
        explained += combos_by_id[ship_build.combo_id].score_delta_2x * ship_build.count
    return explained


def classify_ship_first_family(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> ShipFirstFamily | None:
    """Structural family for an in-regime ship-first near-solution.

    Non-torp military above ``observed + slack`` is mine-overshoot, even when
    modest torps inflate leftover. Otherwise torps lifting the total above slack
    are ammo-top-up. Leftover-0 exact is untagged.
    """
    actions_by_id, combos_by_id = _catalog_lookups(catalog)
    explained = catalog_explained_military_delta_2x(solution, actions_by_id, combos_by_id)
    slack = observation.military_partition_slack_2x
    if explained - observation.military_delta_2x <= slack:
        return None
    if non_torp_military_2x(solution, catalog) > observation.military_delta_2x + slack:
        return "mine_overshoot"
    return "ammo_top_up"


def tag_ship_first_near_solution(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> InferenceSolution:
    """Return ``solution`` with Core ``ship_first_family`` set (or cleared)."""
    return replace(
        solution,
        ship_first_family=classify_ship_first_family(solution, observation, catalog),
    )


def _rank_key(
    solution: InferenceSolution,
    leftover_2x: Callable[[InferenceSolution], int],
) -> tuple[int, int]:
    return (-solution.objective_value, leftover_2x(solution))


def _family_counts(solutions: list[InferenceSolution]) -> dict[ShipFirstFamily, int]:
    counts: dict[ShipFirstFamily, int] = {"mine_overshoot": 0, "ammo_top_up": 0}
    for solution in solutions:
        family = solution.ship_first_family
        if family is not None:
            counts[family] += 1
    return counts


def _insert_ranked(
    solutions: list[InferenceSolution],
    candidate: InferenceSolution,
    leftover_2x: Callable[[InferenceSolution], int],
) -> None:
    keys = [_rank_key(held, leftover_2x) for held in solutions]
    index = bisect_right(keys, _rank_key(candidate, leftover_2x))
    solutions.insert(index, candidate)


def admit_ship_first_ranked_solution(
    solutions: list[InferenceSolution],
    seen_signatures: set[SolutionSignature],
    candidate: InferenceSolution,
    *,
    max_solutions: int,
    leftover_2x: Callable[[InferenceSolution], int],
    on_admitted: Callable[[InferenceSolution], None] | None = None,
) -> bool:
    """Admit ``candidate`` under ship-first stratified hold.

    When both families have hits, keep a floor of
    :data:`SHIP_FIRST_FAMILY_HOLD_FLOOR` each (or every hit if fewer). Remaining
    slots follow rank weight then leftover. One family may fill all K.
    """
    if max_solutions <= 0:
        return False
    signature = solution_signature(candidate)
    if signature in seen_signatures:
        return False
    if len(solutions) < max_solutions:
        seen_signatures.add(signature)
        _insert_ranked(solutions, candidate, leftover_2x)
        if on_admitted is not None:
            on_admitted(candidate)
        return True

    pool = [*solutions, candidate]
    pool_counts = _family_counts(pool)
    mixed = pool_counts["mine_overshoot"] > 0 and pool_counts["ammo_top_up"] > 0

    def quota(family: ShipFirstFamily) -> int:
        if not mixed:
            return 0
        return min(SHIP_FIRST_FAMILY_HOLD_FLOOR, pool_counts[family])

    eligible: list[InferenceSolution] = []
    for held in solutions:
        resulting_counts = _family_counts(
            [solution for solution in solutions if solution is not held] + [candidate]
        )
        if mixed and any(
            resulting_counts[family] < quota(family) for family in ("mine_overshoot", "ammo_top_up")
        ):
            continue
        eligible.append(held)
    if not eligible:
        return False

    victim = max(eligible, key=lambda solution: _rank_key(solution, leftover_2x))
    held_counts = _family_counts(solutions)
    candidate_family = candidate.ship_first_family
    floor_fill = (
        mixed
        and candidate_family is not None
        and held_counts[candidate_family] < SHIP_FIRST_FAMILY_HOLD_FLOOR
    )
    if _rank_key(candidate, leftover_2x) >= _rank_key(victim, leftover_2x) and not floor_fill:
        return False

    seen_signatures.remove(solution_signature(victim))
    solutions.remove(victim)
    seen_signatures.add(signature)
    _insert_ranked(solutions, candidate, leftover_2x)
    if on_admitted is not None:
        on_admitted(candidate)
    return True
