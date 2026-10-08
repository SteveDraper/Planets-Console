"""Admit newly widened labels for a score class the ladder already holds.

Search merges fittings that share military score and ship counts into one
variable, and a held solution no-goods that variable so later tiers look for a
new structure. Expansion is what chooses the hull label. When a later tier
adds fittings to a class that is already held, expand the held assignment
again and admit any new label the current catalog ranks into the top K.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.near_best_structural_search import (
    merged_assignment_from_solution,
)
from api.analytics.military_score_inference.solver import (
    expand_structural_hits_to_top_k,
    merge_score_equivalent_combos,
)

ScoreClassKey = tuple[int, int, int]


def relabel_held_score_equivalent_solutions(
    held_solutions: Sequence[InferenceSolution],
    catalog: ActionCatalog,
    observation: InferenceObservation,
    *,
    added_combo_ids: frozenset[str],
    admit: Callable[[InferenceSolution], None],
    race_id: int | None = None,
    max_solutions: int,
) -> None:
    """Re-expand held score classes that gained members in ``added_combo_ids``.

    ``admit`` may insert into ``held_solutions``. Expansion walks a snapshot so
    those inserts are not visited as further held rows.
    """
    if not held_solutions or not added_combo_ids:
        return
    held_snapshot = tuple(held_solutions)
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    if not _added_combo_joins_held_class(held_snapshot, combos_by_id, added_combo_ids):
        return

    problem = build_inference_problem(
        observation,
        catalog,
        race_id=race_id,
        max_solutions=max_solutions,
    )
    merged = merge_score_equivalent_combos(problem.ship_build_combos)
    affected_merged_ids = _merged_ids_for_combos(merged.members_by_merged_id, added_combo_ids)
    if not affected_merged_ids:
        return

    seen_assignments: set[tuple[tuple[str, int], ...]] = set()
    structural_hits: list[tuple[dict[str, int], dict[str, int]]] = []
    for held in held_snapshot:
        mapped = merged_assignment_from_solution(
            held,
            problem=problem,
            merged_combo_catalog=merged,
        )
        if mapped is None:
            continue
        action_counts, combo_counts = mapped
        active_merged_ids = {combo_id for combo_id, count in combo_counts.items() if count > 0}
        if not active_merged_ids & affected_merged_ids:
            continue
        assignment_key = tuple(sorted(action_counts.items()) + sorted(combo_counts.items()))
        if assignment_key in seen_assignments:
            continue
        seen_assignments.add(assignment_key)
        structural_hits.append((action_counts, combo_counts))

    for expansion in expand_structural_hits_to_top_k(
        problem,
        structural_hits,
        merged,
        max_solutions=max_solutions,
    ):
        admit(expansion)


def _added_combo_joins_held_class(
    held_solutions: Sequence[InferenceSolution],
    combos_by_id: dict[str, ShipBuildCombo],
    added_combo_ids: frozenset[str],
) -> bool:
    held_keys: set[ScoreClassKey] = set()
    for solution in held_solutions:
        for ship_build in solution.ship_builds:
            combo = combos_by_id.get(ship_build.combo_id)
            if combo is None:
                continue
            held_keys.add(_score_class_key(combo))
    if not held_keys:
        return False
    for combo_id in added_combo_ids:
        combo = combos_by_id.get(combo_id)
        if combo is not None and _score_class_key(combo) in held_keys:
            return True
    return False


def _score_class_key(combo: ShipBuildCombo) -> ScoreClassKey:
    return (combo.score_delta_2x, combo.warship_delta, combo.freighter_delta)


def _merged_ids_for_combos(
    members_by_merged_id: dict[str, tuple[ShipBuildCombo, ...]],
    combo_ids: frozenset[str],
) -> set[str]:
    merged_ids: set[str] = set()
    for merged_id, members in members_by_merged_id.items():
        if any(member.combo_id in combo_ids for member in members):
            merged_ids.add(merged_id)
    return merged_ids
