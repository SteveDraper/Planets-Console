"""Ship-first family tag and stratified hold (design §3.11)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
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
from api.analytics.military_score_inference.ship_first_overshoot import leftover_military_2x

SHIP_FIRST_FAMILY_HOLD_FLOOR = 3
_HOLD_FAMILIES: tuple[ShipFirstFamily, ShipFirstFamily] = ("mine_overshoot", "ammo_top_up")

__all__ = (
    "SHIP_FIRST_FAMILY_HOLD_FLOOR",
    "admit_ship_first_ranked_solution",
    "classify_ship_first_family",
    "is_ship_first_overshoot_list",
    "non_torp_military_2x",
    "select_ship_first_hold",
    "tag_ship_first_near_solution",
)


def is_ship_first_overshoot_list(solutions: Iterable[InferenceSolution]) -> bool:
    """True when the held list is overshooting near-solutions, not leftover-0 exact.

    Incremental ``solution`` events stay leftover-0 / exact only; overshooting
    ship-first lists ride on terminal ``complete``.
    """
    return any(solution.ship_first_family is not None for solution in solutions)


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
    without_torps = replace(
        solution,
        actions=tuple(
            action for action in solution.actions if not is_torp_load_action_id(action.action_id)
        ),
    )
    return catalog_explained_military_delta_2x(without_torps, actions_by_id, combos_by_id)


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
    leftover = leftover_military_2x(solution, observation, catalog)
    slack = observation.military_partition_slack_2x
    if leftover <= slack:
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
    counts: dict[ShipFirstFamily, int] = dict.fromkeys(_HOLD_FAMILIES, 0)
    for solution in solutions:
        family = solution.ship_first_family
        if family is not None:
            counts[family] += 1
    return counts


def _take_family_floor(
    ranked: list[InferenceSolution],
    family: ShipFirstFamily,
    take: int,
) -> tuple[list[InferenceSolution], list[InferenceSolution]]:
    kept: list[InferenceSolution] = []
    rest: list[InferenceSolution] = []
    for solution in ranked:
        if take and solution.ship_first_family == family:
            kept.append(solution)
            take -= 1
        else:
            rest.append(solution)
    return kept, rest


def select_ship_first_hold(
    pool: list[InferenceSolution],
    k: int,
    leftover_2x: Callable[[InferenceSolution], int],
) -> list[InferenceSolution]:
    """Select up to ``k`` solutions from ``pool`` under stratified hold.

    Mixed families: floor of :data:`SHIP_FIRST_FAMILY_HOLD_FLOOR` each (or every
    hit if fewer), then remaining slots by rank weight then leftover. One family:
    top-K by the same key. When ``2 * floor > k``, take the best of each family
    first until ``k`` is full.
    """
    if k <= 0:
        return []
    ranked = sorted(pool, key=lambda solution: _rank_key(solution, leftover_2x))
    counts = _family_counts(pool)
    mixed = all(counts[family] > 0 for family in _HOLD_FAMILIES)
    if not mixed:
        return ranked[:k]
    selected: list[InferenceSolution] = []
    remaining = ranked
    for family in _HOLD_FAMILIES:
        take = min(SHIP_FIRST_FAMILY_HOLD_FLOOR, counts[family])
        kept, remaining = _take_family_floor(remaining, family, take)
        selected.extend(kept)
    selected.extend(remaining)
    selected = selected[:k]
    selected.sort(key=lambda solution: _rank_key(solution, leftover_2x))
    return selected


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
    proposed = select_ship_first_hold(
        [*solutions, candidate],
        max_solutions,
        leftover_2x,
    )
    if not any(held is candidate for held in proposed):
        return False
    dropped = {solution_signature(held) for held in solutions} - {
        solution_signature(kept) for kept in proposed
    }
    seen_signatures.difference_update(dropped)
    seen_signatures.add(signature)
    solutions[:] = proposed
    if on_admitted is not None:
        on_admitted(candidate)
    return True
