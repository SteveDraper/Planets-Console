"""Admit newly widened labels for a score class the ladder already holds.

Search merges fittings that share military score and ship counts into one
variable, and a held solution no-goods that variable so later tiers look for a
new structure. Expansion is what chooses the hull label. When a later tier
adds fittings to a class that is already held, expand the held assignment
again and admit any new label the current catalog ranks into the top K.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
)
from api.analytics.military_score_inference.near_best_structural_search import (
    member_combo_id_to_merged_id,
    merged_assignment_from_solution,
)
from api.analytics.military_score_inference.ranked_solution_buffer import (
    SolutionSignature,
    solution_signature,
)
from api.analytics.military_score_inference.solver import (
    expand_structural_hits_to_top_k,
    merge_score_equivalent_combos,
)


def relabel_held_score_equivalent_solutions(
    held_solutions: Sequence[InferenceSolution],
    catalog: ActionCatalog,
    observation: InferenceObservation,
    *,
    added_combo_ids: frozenset[str],
    overshoot_signatures: Collection[SolutionSignature],
    admit: Callable[[InferenceSolution], None],
    race_id: int | None = None,
    max_solutions: int,
) -> None:
    """Re-expand held score classes that gained members in ``added_combo_ids``.

    ``admit`` may insert into ``held_solutions``. Expansion walks a snapshot so
    those inserts are not visited as further held rows. Signatures in
    ``overshoot_signatures`` stay on the leftover-ranked buffer.
    """
    if not held_solutions or not added_combo_ids:
        return
    # Leftover-ranked overshoot holds are not exact top-K rows.
    held_snapshot = tuple(
        held for held in held_solutions if solution_signature(held) not in overshoot_signatures
    )
    if not held_snapshot:
        return

    problem = build_inference_problem(
        observation,
        catalog,
        race_id=race_id,
        max_solutions=max_solutions,
    )
    merged = merge_score_equivalent_combos(problem.ship_build_combos)
    member_to_merged = member_combo_id_to_merged_id(merged)
    affected_merged_ids = {
        member_to_merged[combo_id] for combo_id in added_combo_ids if combo_id in member_to_merged
    }
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
