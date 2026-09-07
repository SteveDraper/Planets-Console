"""Exact-merge admission and ladder early-stop helpers for one policy tier."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.constraints import (
    solution_satisfies_exact_hard_equalities,
)
from api.analytics.military_score_inference.hopeless_classifier import (
    CHEAP_LADDER_LAST_STEP_ID,
    classify_hopeless_abort,
    leftover_2x_after_construction_envelope,
    min_warship_score_delta_2x,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.ranked_solution_buffer import (
    SolutionSignature,
    admit_ranked_solutions,
    solution_signature,
)
from api.analytics.military_score_inference.ship_first_overshoot import (
    SHIP_FIRST_PREFIX_LAST_STEP_ID,
    SHIP_FIRST_PREFIX_STOP_REASON,
)
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    resolve_solver_thresholds,
)

__all__ = (
    "held_leftover_0_solutions",
    "leftover_0_solutions",
    "make_incremental_admitter",
    "maybe_early_stop_after_step",
    "maybe_expensive_tier_abort_after_step",
    "maybe_no_new_exact_signatures_early_stop",
    "maybe_ship_first_prefix_stop_after_step",
    "solution_is_leftover_0_exact",
)


def _best_merged_solution(
    merged_solutions: list[InferenceSolution],
) -> InferenceSolution | None:
    if not merged_solutions:
        return None
    return max(merged_solutions, key=lambda solution: solution.objective_value)


def solution_is_leftover_0_exact(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    admitted_under_overshoot: bool = False,
) -> bool:
    """True when an exact-pass hit matches observed military within slack.

    Envelope coverage is the exact-pass leftover-0 test because that solve is
    pinned into ``observed ± slack``. Overshoot admits are never leftover-0:
    the window already required leftover strictly above slack.
    """
    if admitted_under_overshoot:
        return False
    return solution_satisfies_exact_hard_equalities(solution, observation, catalog)


def leftover_0_solutions(
    solutions: Iterable[InferenceSolution],
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    overshoot_signatures: Collection[SolutionSignature],
) -> list[InferenceSolution]:
    """Exact-pass leftover-0 hits; overshoot admits are excluded."""
    return [
        solution
        for solution in solutions
        if solution_is_leftover_0_exact(
            solution,
            observation,
            catalog,
            admitted_under_overshoot=solution_signature(solution) in overshoot_signatures,
        )
    ]


def held_leftover_0_solutions(
    state: PolicyLadderState,
    observation: InferenceObservation,
    catalog: ActionCatalog | None,
) -> bool:
    """True when merged top-K contains an exact-pass leftover-0 hit against ``catalog``."""
    if catalog is None:
        return bool(state.merged_solutions)
    return bool(
        leftover_0_solutions(
            state.merged_solutions,
            observation,
            catalog,
            overshoot_signatures=state.overshoot_signatures,
        )
    )


def maybe_ship_first_prefix_stop_after_step(
    state: PolicyLadderState,
    *,
    policy_step: InferenceTierPolicyStep,
) -> bool:
    """Stop after ``admit_ship_torpedoes`` so in-regime search never admits planet/SB posts."""
    plan = state.ship_first_overshoot
    if plan is None or not plan.is_in_regime:
        return False
    if policy_step.id != SHIP_FIRST_PREFIX_LAST_STEP_ID:
        return False
    state.ladder_complete = True
    state.ladder_early_stop_reason = SHIP_FIRST_PREFIX_STOP_REASON
    return True


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


def maybe_early_stop_after_step(
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


def maybe_no_new_exact_signatures_early_stop(
    state: PolicyLadderState,
    *,
    added_combo_ids: frozenset[str],
    added_aggregate_action_ids: frozenset[str],
    new_exact_before_step: int,
) -> bool:
    """Return True when catalog growth was a noop and best leftover-0 exact is plausible enough."""
    if state.ship_first_overshoot is not None and state.ship_first_overshoot.is_in_regime:
        return False
    if len(state.merged_solutions) != new_exact_before_step:
        return False
    if not state.merged_solutions:
        return False
    if added_combo_ids or added_aggregate_action_ids:
        return False
    best_solution = _best_merged_solution(state.merged_solutions)
    if best_solution is None:
        return False
    thresholds = resolve_solver_thresholds()
    if (
        best_solution.objective_value
        < thresholds.no_new_exact_signatures_early_stop_min_plausibility
    ):
        return False
    state.ladder_complete = True
    state.ladder_early_stop_reason = "no_new_exact_signatures"
    return True


def maybe_expensive_tier_abort_after_step(
    state: PolicyLadderState,
    *,
    policy_step: InferenceTierPolicyStep,
    observation: InferenceObservation,
    catalog: ActionCatalog | None,
) -> bool:
    """Stop before fighter / SB-post / raised-cap steps when the hopeless classifier fires."""
    if policy_step.id != CHEAP_LADDER_LAST_STEP_ID:
        return False
    if state.cancelled or state.time_limited:
        return False
    if state.hopeless_context is None:
        return False
    facts = state.hopeless_context
    if catalog is not None and any(
        solution_satisfies_exact_hard_equalities(solution, observation, catalog)
        for solution in state.merged_solutions
    ):
        return False
    if catalog is None and state.merged_solutions:
        return False
    leftover_2x = leftover_2x_after_construction_envelope(
        observation.military_delta_2x,
        observation.warship_delta,
        min_warship_score_delta_2x(catalog),
    )
    decision = classify_hopeless_abort(
        facts,
        leftover_2x=leftover_2x,
        warship_delta=observation.warship_delta,
    )
    if not decision.abort or decision.status is None:
        return False
    state.ladder_complete = True
    state.ladder_early_stop_reason = "expensive_tier_abort"
    state.last_status = decision.status
    return True


def make_incremental_admitter(
    state: PolicyLadderState,
    on_admitted: Callable[[InferenceSolution], None] | None,
) -> Callable[[InferenceSolution], None]:
    """Merge each solver solution into held top-K as soon as it is found."""

    def admit(solution: InferenceSolution) -> None:
        admit_ranked_solutions(
            state.merged_solutions,
            state.seen_signatures,
            (solution,),
            max_solutions=state.resolved_max_solutions,
            on_admitted=on_admitted,
        )

    return admit
