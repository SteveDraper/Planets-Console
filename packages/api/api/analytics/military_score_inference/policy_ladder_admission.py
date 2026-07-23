"""Exact-merge admission and ladder early-stop helpers for one policy tier."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.constraints import (
    solution_satisfies_exact_hard_equalities,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.solver import solution_signature
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    resolve_solver_thresholds,
)


def _best_merged_solution(
    merged_solutions: list[InferenceSolution],
) -> InferenceSolution | None:
    if not merged_solutions:
        return None
    return max(merged_solutions, key=lambda solution: solution.objective_value)


def _solution_fully_explained_by_ship_builds_only(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    if solution.actions:
        return False
    return solution_satisfies_exact_hard_equalities(solution, observation, catalog)


def _solution_qualifies_for_ship_only_exact_early_stop(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    if not _solution_fully_explained_by_ship_builds_only(solution, observation, catalog):
        return False
    thresholds = resolve_solver_thresholds()
    return solution.objective_value >= thresholds.ship_only_exact_early_stop_min_plausibility


def _merge_exact_solutions(
    merged_solutions: list[InferenceSolution],
    seen_signatures: set[tuple[tuple[str, int], ...]],
    candidates: tuple[InferenceSolution, ...],
    *,
    resolved_max_solutions: int,
    on_admitted: Callable[[InferenceSolution], None] | None = None,
) -> int:
    new_solutions = 0
    for solution in candidates:
        signature = solution_signature(solution)
        if signature in seen_signatures:
            continue
        if len(merged_solutions) < resolved_max_solutions:
            seen_signatures.add(signature)
            merged_solutions.append(solution)
            new_solutions += 1
            if on_admitted is not None:
                on_admitted(solution)
            continue
        worst_index = min(
            range(len(merged_solutions)),
            key=lambda index: merged_solutions[index].objective_value,
        )
        worst_solution = merged_solutions[worst_index]
        if solution.objective_value <= worst_solution.objective_value:
            continue
        seen_signatures.remove(solution_signature(worst_solution))
        seen_signatures.add(signature)
        merged_solutions[worst_index] = solution
        new_solutions += 1
        if on_admitted is not None:
            on_admitted(solution)
    return new_solutions


def _maybe_early_stop_after_step(
    state: PolicyLadderState,
    *,
    policy_step: InferenceTierPolicyStep,
    observation: InferenceObservation,
    catalog: ActionCatalog | None,
) -> bool:
    """Return True when the ladder should stop after this completed step."""
    if not policy_step.allow_ship_only_exact_early_stop:
        return False
    if catalog is None:
        return False
    best_solution = _best_merged_solution(state.merged_solutions)
    if best_solution is None:
        return False
    if not _solution_qualifies_for_ship_only_exact_early_stop(
        best_solution,
        observation,
        catalog,
    ):
        return False
    state.ladder_complete = True
    state.ladder_early_stop_reason = "ship_only_exact_early_stop"
    return True


def _maybe_no_new_exact_signatures_early_stop(
    state: PolicyLadderState,
    *,
    added_combo_ids: frozenset[str],
    added_aggregate_action_ids: frozenset[str],
    new_exact_before_step: int,
) -> bool:
    """Return True when catalog growth was a noop and best exact is plausible enough."""
    if len(state.merged_solutions) != new_exact_before_step:
        return False
    if not state.merged_solutions:
        return False
    if added_combo_ids or added_aggregate_action_ids:
        return False
    best_solution = _best_merged_solution(state.merged_solutions)
    # Emptiness already gated above; _best_merged_solution only returns None for [].
    assert best_solution is not None
    thresholds = resolve_solver_thresholds()
    if (
        best_solution.objective_value
        < thresholds.no_new_exact_signatures_early_stop_min_plausibility
    ):
        return False
    state.ladder_complete = True
    state.ladder_early_stop_reason = "no_new_exact_signatures"
    return True


def _make_incremental_admitter(
    state: PolicyLadderState,
    on_admitted: Callable[[InferenceSolution], None] | None,
) -> Callable[[InferenceSolution], None]:
    """Merge each solver solution into held top-K as soon as it is found."""

    def admit(solution: InferenceSolution) -> None:
        _merge_exact_solutions(
            state.merged_solutions,
            state.seen_signatures,
            (solution,),
            resolved_max_solutions=state.resolved_max_solutions,
            on_admitted=on_admitted,
        )

    return admit
