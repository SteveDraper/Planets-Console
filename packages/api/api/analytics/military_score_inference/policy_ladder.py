"""YAML tier policy ladder execution: walk steps, seed carry-forward, merge solutions."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from api.analytics.military_score_inference.actions import (
    DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    ActionCatalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.component_eligibility import (
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
    solution_signature,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    resolve_tier_policies,
)
from api.models.game import TurnInfo


@dataclass
class PolicyLadderState:
    """Mutable cross-tier state for one policy-ladder row run."""

    policy_steps: tuple[InferenceTierPolicyStep, ...]
    policy_steps_attempted: list[str] = field(default_factory=list)
    step_diagnostics: list[dict[str, object]] = field(default_factory=list)
    merged_solutions: list[InferenceSolution] = field(default_factory=list)
    seen_signatures: set[tuple[tuple[str, int], ...]] = field(default_factory=set)
    catalog: ActionCatalog | None = None
    problem: InferenceProblem | None = None
    last_status: str = STATUS_NO_EXACT_SOLUTION
    last_diagnostics: dict[str, object] = field(default_factory=dict)
    resolved_max_solutions: int = 20
    time_limited: bool = False
    band_seeds: list[InferenceSolution] = field(default_factory=list)
    best_band_residual_2x: int | None = None
    prior_combo_ids: frozenset[str] | None = None
    prior_aggregate_action_ids: frozenset[str] | None = None
    ladder_early_stop_reason: str | None = None
    next_step_index: int = 0
    ladder_complete: bool = False
    cancelled: bool = False
    started_at: float = field(default_factory=time.monotonic)
    resolved_mask: ResolvedHullCatalogMask | None = None


def _remaining_time(started_at: float, time_limit_seconds: float | None) -> float:
    if time_limit_seconds is None:
        return float("inf")
    return time_limit_seconds - (time.monotonic() - started_at)


def _combo_counts_from_solution(solution: InferenceSolution) -> dict[str, int]:
    return {ship_build.combo_id: ship_build.count for ship_build in solution.ship_builds}


def _solution_fully_explained_by_ship_builds_only(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    if solution.actions:
        return False
    return _solution_satisfies_exact_hard_equalities(solution, observation, catalog)


def _solution_satisfies_exact_hard_equalities(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    military_sum = 0
    warship_sum = 0
    freighter_sum = 0
    for action in solution.actions:
        catalog_action = actions_by_id.get(action.action_id)
        if catalog_action is None:
            return False
        military_sum += catalog_action.score_delta_2x * action.count
        warship_sum += catalog_action.warship_delta * action.count
        freighter_sum += catalog_action.freighter_delta * action.count
    for ship_build in solution.ship_builds:
        combo = combos_by_id.get(ship_build.combo_id)
        if combo is None:
            return False
        military_sum += combo.score_delta_2x * ship_build.count
        warship_sum += combo.warship_delta * ship_build.count
        freighter_sum += combo.freighter_delta * ship_build.count
    return (
        abs(military_sum - observation.military_delta_2x) <= observation.military_partition_slack_2x
        and warship_sum == observation.warship_delta
        and freighter_sum == observation.freighter_delta
    )


def _explained_military_score_2x(
    solution: InferenceSolution,
    catalog: ActionCatalog,
) -> int:
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    explained = 0
    for action in solution.actions:
        catalog_action = actions_by_id[action.action_id]
        explained += catalog_action.score_delta_2x * action.count
    for ship_build in solution.ship_builds:
        combo = combos_by_id[ship_build.combo_id]
        explained += combo.score_delta_2x * ship_build.count
    return explained


def _catalog_solve_max_solutions(merged_count: int, resolved_max_solutions: int) -> int:
    remaining_slots = max(0, resolved_max_solutions - merged_count)
    if remaining_slots > 0:
        return remaining_slots
    return resolved_max_solutions


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


def _solve_catalog(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    max_solutions: int,
    time_limit_seconds: float,
    military_score_alpha: int = 0,
    fixed_combo_counts: dict[str, int] | None = None,
    combo_count_neighborhood: int = 0,
    cancel_token: InferenceCancelToken | None = None,
    on_solution: Callable[[InferenceSolution], None] | None = None,
) -> tuple[InferenceResult, InferenceProblem]:
    problem = build_inference_problem(
        observation,
        catalog,
        max_solutions=max_solutions,
        time_limit_seconds=time_limit_seconds,
        military_score_alpha=military_score_alpha,
        fixed_combo_counts=fixed_combo_counts,
        combo_count_neighborhood=combo_count_neighborhood,
    )
    return (
        solve_inference_problem(
            problem,
            cancel_token=cancel_token,
            on_solution=on_solution,
        ),
        problem,
    )


def _solve_seed_progression(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    seed: InferenceSolution,
    *,
    max_solutions: int,
    time_limit_seconds: float,
    cancel_token: InferenceCancelToken | None = None,
    on_solution: Callable[[InferenceSolution], None] | None = None,
) -> tuple[InferenceResult | None, InferenceProblem | None]:
    fixed_counts = _combo_counts_from_solution(seed)
    if not fixed_counts:
        return None, None

    remaining_slots = max_solutions
    for neighborhood in (0, 1):
        if remaining_slots <= 0 or time_limit_seconds <= 0:
            break
        if cancel_token is not None and cancel_token.is_cancelled():
            break
        result, problem = _solve_catalog(
            observation,
            catalog,
            max_solutions=remaining_slots,
            time_limit_seconds=time_limit_seconds,
            fixed_combo_counts=fixed_counts,
            combo_count_neighborhood=neighborhood,
            cancel_token=cancel_token,
            on_solution=on_solution,
        )
        if result.status == STATUS_STOPPED:
            return result, problem
        if result.solutions:
            return result, problem

    if cancel_token is not None and cancel_token.is_cancelled():
        return None, None

    result, problem = _solve_catalog(
        observation,
        catalog,
        max_solutions=remaining_slots,
        time_limit_seconds=time_limit_seconds,
        cancel_token=cancel_token,
        on_solution=on_solution,
    )
    if result.solutions or result.status == STATUS_STOPPED:
        return result, problem
    return None, None


def _policy_step_diagnostics(
    *,
    policy_step: InferenceTierPolicyStep,
    policy_step_index: int,
    catalog: ActionCatalog,
    turn: TurnInfo,
    observation: InferenceObservation,
    seed_count: int,
    band_residual_2x: int | None,
) -> dict[str, object]:
    catalog_context = turn_catalog_context_for_policy_step(
        turn,
        observation.player_id,
        policy_step,
    )
    return {
        "policyStepId": policy_step.id,
        "policyStepIndex": policy_step_index,
        "policyStepsAttempted": policy_step_index + 1,
        "constraintSnapshot": policy_step.constraint_snapshot(),
        "resolvedEligibleEngineIds": sorted(catalog_context.eligible_engine_ids),
        "resolvedEligibleBeamIds": sorted(catalog_context.eligible_beam_ids),
        "resolvedEligibleTorpIds": sorted(catalog_context.eligible_torp_ids),
        "resolvedBuildableHullIds": sorted(catalog_context.buildable_hull_ids),
        "alpha": policy_step.alpha,
        "comboCount": len(catalog.ship_build_combos),
        "seedCount": seed_count,
        "bandResidual2x": band_residual_2x,
    }


def run_policy_ladder_tier_step(
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    time_limit_seconds: float | None,
    cancel_token: InferenceCancelToken | None = None,
    on_admitted: Callable[[InferenceSolution], None] | None = None,
) -> None:
    """Run one inference search tier step; mutates ``state`` in place."""
    if state.ladder_complete or state.next_step_index >= len(state.policy_steps):
        state.ladder_complete = True
        return

    if cancel_token is not None and cancel_token.is_cancelled():
        state.cancelled = True
        state.ladder_complete = True
        return

    remaining = _remaining_time(state.started_at, time_limit_seconds)
    if remaining <= 0:
        state.time_limited = True
        state.ladder_complete = True
        return

    step_index = state.next_step_index
    policy_step = state.policy_steps[step_index]
    state.policy_steps_attempted.append(policy_step.id)
    catalog = build_action_catalog_from_turn(
        observation,
        turn,
        policy_step=policy_step,
        policy_step_index=step_index,
        resolved_mask=state.resolved_mask,
    )
    state.catalog = catalog
    current_combo_ids = frozenset(combo.combo_id for combo in catalog.ship_build_combos)
    added_combo_ids = (
        current_combo_ids
        if state.prior_combo_ids is None
        else current_combo_ids - state.prior_combo_ids
    )
    state.prior_combo_ids = current_combo_ids
    current_aggregate_action_ids = frozenset(action.id for action in catalog.aggregate_actions)
    added_aggregate_action_ids = (
        current_aggregate_action_ids
        if state.prior_aggregate_action_ids is None
        else current_aggregate_action_ids - state.prior_aggregate_action_ids
    )
    state.prior_aggregate_action_ids = current_aggregate_action_ids

    catalog_solve_max = _catalog_solve_max_solutions(
        len(state.merged_solutions),
        state.resolved_max_solutions,
    )

    new_exact_before_step = len(state.merged_solutions)
    seeds_for_step = list(state.band_seeds)
    state.band_seeds = []

    for seed in seeds_for_step[: policy_step.max_seeds]:
        if cancel_token is not None and cancel_token.is_cancelled():
            state.cancelled = True
            state.ladder_complete = True
            return
        seed_remaining = _remaining_time(state.started_at, time_limit_seconds)
        if seed_remaining <= 0:
            state.time_limited = True
            state.ladder_complete = True
            return
        seed_result, seed_problem = _solve_seed_progression(
            observation,
            catalog,
            seed,
            max_solutions=catalog_solve_max,
            time_limit_seconds=seed_remaining,
            cancel_token=cancel_token,
        )
        if seed_result is None or seed_problem is None:
            continue
        if seed_result.status == STATUS_INVALID_PROBLEM:
            state.last_status = seed_result.status
            state.last_diagnostics = dict(seed_result.diagnostics)
            state.problem = seed_problem
            state.ladder_complete = True
            return
        if seed_result.status == STATUS_STOPPED:
            state.cancelled = True
            state.last_status = seed_result.status
            state.last_diagnostics = dict(seed_result.diagnostics)
            state.problem = seed_problem
            state.ladder_complete = True
            return
        catalog_solve_max = _catalog_solve_max_solutions(
            len(state.merged_solutions),
            state.resolved_max_solutions,
        )
        _merge_exact_solutions(
            state.merged_solutions,
            state.seen_signatures,
            seed_result.solutions,
            resolved_max_solutions=state.resolved_max_solutions,
            on_admitted=on_admitted,
        )
        state.problem = seed_problem
        if seed_result.status == STATUS_TIME_LIMITED:
            state.time_limited = True

    if state.last_status == STATUS_INVALID_PROBLEM:
        state.ladder_complete = True
        return

    if cancel_token is not None and cancel_token.is_cancelled():
        state.cancelled = True
        state.ladder_complete = True
        return

    remaining = _remaining_time(state.started_at, time_limit_seconds)
    if remaining <= 0:
        state.time_limited = True
        state.ladder_complete = True
        return
    catalog_solve_max = _catalog_solve_max_solutions(
        len(state.merged_solutions),
        state.resolved_max_solutions,
    )

    exact_result, problem = _solve_catalog(
        observation,
        catalog,
        max_solutions=catalog_solve_max,
        time_limit_seconds=remaining,
        cancel_token=cancel_token,
    )
    state.last_status = exact_result.status
    state.last_diagnostics = dict(exact_result.diagnostics)
    state.problem = problem
    if exact_result.status == STATUS_INVALID_PROBLEM:
        state.ladder_complete = True
        return
    if exact_result.status == STATUS_STOPPED:
        state.cancelled = True
        state.ladder_complete = True
        return

    if exact_result.solutions:
        _merge_exact_solutions(
            state.merged_solutions,
            state.seen_signatures,
            exact_result.solutions,
            resolved_max_solutions=state.resolved_max_solutions,
            on_admitted=on_admitted,
        )
        if exact_result.status == STATUS_TIME_LIMITED:
            state.time_limited = True

    band_residual_2x: int | None = None
    if not exact_result.solutions and policy_step.alpha > 0:
        remaining = _remaining_time(state.started_at, time_limit_seconds)
        if remaining > 0 and not (cancel_token is not None and cancel_token.is_cancelled()):
            band_result, band_problem = _solve_catalog(
                observation,
                catalog,
                max_solutions=policy_step.max_seeds,
                time_limit_seconds=remaining,
                military_score_alpha=policy_step.alpha,
                cancel_token=cancel_token,
            )
            state.problem = band_problem
            state.last_diagnostics = dict(band_result.diagnostics)
            if band_result.status == STATUS_STOPPED:
                state.cancelled = True
                state.ladder_complete = True
                return
            if band_result.solutions:
                state.band_seeds = list(band_result.solutions[: policy_step.max_seeds])
                best_solution = band_result.solutions[0]
                explained = _explained_military_score_2x(best_solution, catalog)
                band_residual_2x = observation.military_delta_2x - explained
                if (
                    state.best_band_residual_2x is None
                    or band_residual_2x < state.best_band_residual_2x
                ):
                    state.best_band_residual_2x = band_residual_2x
            elif band_result.status == STATUS_INVALID_PROBLEM:
                state.last_status = band_result.status
                state.ladder_complete = True
                return

    state.step_diagnostics.append(
        _policy_step_diagnostics(
            policy_step=policy_step,
            policy_step_index=step_index,
            catalog=catalog,
            turn=turn,
            observation=observation,
            seed_count=len(seeds_for_step),
            band_residual_2x=band_residual_2x,
        )
    )

    state.next_step_index = step_index + 1

    if state.merged_solutions and _solution_fully_explained_by_ship_builds_only(
        state.merged_solutions[0],
        observation,
        catalog,
    ):
        state.ladder_complete = True
        return

    if (
        len(state.merged_solutions) == new_exact_before_step
        and len(state.merged_solutions) > 0
        and not added_combo_ids
        and not added_aggregate_action_ids
    ):
        state.ladder_early_stop_reason = "no_new_exact_signatures"
        state.ladder_complete = True
        return

    if state.next_step_index >= len(state.policy_steps):
        state.ladder_complete = True


def finalize_policy_ladder_result(
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    max_solutions: int | None = None,
) -> tuple[
    InferenceResult,
    ActionCatalog,
    InferenceProblem,
    list[str],
    list[dict[str, object]],
]:
    """Build the terminal inference result from ladder state."""
    catalog = state.catalog
    problem = state.problem
    merged_solutions = state.merged_solutions

    if catalog is None or problem is None:
        first_step = state.policy_steps[0]
        state.policy_steps_attempted.append(first_step.id)
        catalog = build_action_catalog_from_turn(
            observation,
            turn,
            policy_step=first_step,
            policy_step_index=0,
            resolved_mask=state.resolved_mask,
        )
        problem = build_inference_problem(observation, catalog, max_solutions=max_solutions)
        tier_result = solve_inference_problem(problem)
        state.last_status = tier_result.status
        state.last_diagnostics = dict(tier_result.diagnostics)
        _merge_exact_solutions(
            state.merged_solutions,
            state.seen_signatures,
            tier_result.solutions,
            resolved_max_solutions=state.resolved_max_solutions,
        )
        merged_solutions = state.merged_solutions

    merged_solutions = list(merged_solutions)
    merged_solutions.sort(key=lambda solution: solution.objective_value, reverse=True)

    if state.cancelled:
        status = STATUS_STOPPED
    elif merged_solutions:
        if any(
            _solution_satisfies_exact_hard_equalities(solution, observation, catalog)
            for solution in merged_solutions
        ):
            status = STATUS_EXACT
        elif state.time_limited:
            status = STATUS_TIME_LIMITED
        else:
            status = STATUS_NO_EXACT_SOLUTION
    else:
        status = STATUS_TIME_LIMITED if state.time_limited else state.last_status

    stopped_reason = state.ladder_early_stop_reason or state.last_diagnostics.get(
        "stopped_reason",
        "exhausted",
    )
    if state.cancelled:
        stopped_reason = "cancelled"
    result = InferenceResult(
        status=status,
        solutions=tuple(merged_solutions),
        diagnostics={
            **state.last_diagnostics,
            "policy_step_id": catalog.policy_step_id,
            "policy_step_index": catalog.policy_step_index,
            "solution_count": len(merged_solutions),
            "best_band_residual_2x": state.best_band_residual_2x,
            "stopped_reason": stopped_reason,
        },
    )
    return (
        result,
        catalog,
        problem,
        state.policy_steps_attempted,
        state.step_diagnostics,
    )


def solve_with_policy_ladder(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    policy_path: Path | None = None,
    max_solutions: int | None = None,
    time_limit_seconds: float = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    cancel_token: InferenceCancelToken | None = None,
    on_admitted: Callable[[InferenceSolution], None] | None = None,
    resolved_mask: ResolvedHullCatalogMask | None = None,
) -> tuple[
    InferenceResult,
    ActionCatalog,
    InferenceProblem,
    list[str],
    list[dict[str, object]],
]:
    """Walk the YAML inference search tier ladder with band seed carry-forward."""
    resolved_max_solutions = max_solutions if max_solutions is not None else 20
    state = PolicyLadderState(
        policy_steps=tuple(resolve_tier_policies(policy_path)),
        resolved_max_solutions=resolved_max_solutions,
        resolved_mask=resolved_mask,
    )
    while not state.ladder_complete and state.next_step_index < len(state.policy_steps):
        if cancel_token is not None and cancel_token.is_cancelled():
            state.cancelled = True
            state.ladder_complete = True
            break
        remaining = _remaining_time(state.started_at, time_limit_seconds)
        if remaining <= 0:
            state.time_limited = True
            state.ladder_complete = True
            break
        run_policy_ladder_tier_step(
            state,
            observation,
            turn,
            time_limit_seconds=time_limit_seconds,
            cancel_token=cancel_token,
            on_admitted=on_admitted,
        )
    return finalize_policy_ladder_result(
        state,
        observation,
        turn,
        max_solutions=max_solutions,
    )
