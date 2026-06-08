"""YAML tier policy ladder execution: walk steps, seed carry-forward, merge solutions."""

from __future__ import annotations

import time
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
    STATUS_TIME_LIMITED,
    solution_signature,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    resolve_tier_policies,
)
from api.models.game import TurnInfo


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
    return solve_inference_problem(problem), problem


def _solve_seed_progression(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    seed: InferenceSolution,
    *,
    max_solutions: int,
    time_limit_seconds: float,
) -> tuple[InferenceResult | None, InferenceProblem | None]:
    fixed_counts = _combo_counts_from_solution(seed)
    if not fixed_counts:
        return None, None

    remaining_slots = max_solutions
    for neighborhood in (0, 1):
        if remaining_slots <= 0 or time_limit_seconds <= 0:
            break
        result, problem = _solve_catalog(
            observation,
            catalog,
            max_solutions=remaining_slots,
            time_limit_seconds=time_limit_seconds,
            fixed_combo_counts=fixed_counts,
            combo_count_neighborhood=neighborhood,
        )
        if result.solutions:
            return result, problem

    result, problem = _solve_catalog(
        observation,
        catalog,
        max_solutions=remaining_slots,
        time_limit_seconds=time_limit_seconds,
    )
    if result.solutions:
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


def solve_with_policy_ladder(
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    policy_path: Path | None = None,
    max_solutions: int | None = None,
    time_limit_seconds: float = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> tuple[
    InferenceResult,
    ActionCatalog,
    InferenceProblem,
    list[str],
    list[dict[str, object]],
]:
    """Walk the YAML inference search tier ladder with band seed carry-forward."""
    started_at = time.monotonic()
    policy_steps = resolve_tier_policies(policy_path)
    policy_steps_attempted: list[str] = []
    step_diagnostics: list[dict[str, object]] = []
    merged_solutions: list[InferenceSolution] = []
    seen_signatures: set[tuple[tuple[str, int], ...]] = set()
    catalog: ActionCatalog | None = None
    problem: InferenceProblem | None = None
    last_status = STATUS_NO_EXACT_SOLUTION
    last_diagnostics: dict[str, object] = {}
    resolved_max_solutions = max_solutions if max_solutions is not None else 20
    time_limited = False
    band_seeds: list[InferenceSolution] = []
    best_band_residual_2x: int | None = None
    prior_combo_ids: frozenset[str] | None = None
    prior_aggregate_action_ids: frozenset[str] | None = None
    ladder_early_stop_reason: str | None = None

    for step_index, policy_step in enumerate(policy_steps):
        remaining = time_limit_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            time_limited = True
            break

        policy_steps_attempted.append(policy_step.id)
        catalog = build_action_catalog_from_turn(
            observation,
            turn,
            policy_step=policy_step,
            policy_step_index=step_index,
        )
        current_combo_ids = frozenset(combo.combo_id for combo in catalog.ship_build_combos)
        added_combo_ids = (
            current_combo_ids if prior_combo_ids is None else current_combo_ids - prior_combo_ids
        )
        prior_combo_ids = current_combo_ids
        current_aggregate_action_ids = frozenset(action.id for action in catalog.aggregate_actions)
        added_aggregate_action_ids = (
            current_aggregate_action_ids
            if prior_aggregate_action_ids is None
            else current_aggregate_action_ids - prior_aggregate_action_ids
        )
        prior_aggregate_action_ids = current_aggregate_action_ids

        catalog_solve_max = _catalog_solve_max_solutions(
            len(merged_solutions),
            resolved_max_solutions,
        )

        new_exact_before_step = len(merged_solutions)
        seeds_for_step = list(band_seeds)
        band_seeds = []

        for seed in seeds_for_step[: policy_step.max_seeds]:
            seed_remaining = time_limit_seconds - (time.monotonic() - started_at)
            if seed_remaining <= 0:
                time_limited = True
                break
            seed_result, seed_problem = _solve_seed_progression(
                observation,
                catalog,
                seed,
                max_solutions=catalog_solve_max,
                time_limit_seconds=seed_remaining,
            )
            if seed_result is None or seed_problem is None:
                continue
            if seed_result.status == STATUS_INVALID_PROBLEM:
                last_status = seed_result.status
                last_diagnostics = dict(seed_result.diagnostics)
                problem = seed_problem
                break
            catalog_solve_max = _catalog_solve_max_solutions(
                len(merged_solutions),
                resolved_max_solutions,
            )
            _merge_exact_solutions(
                merged_solutions,
                seen_signatures,
                seed_result.solutions,
                resolved_max_solutions=resolved_max_solutions,
            )
            problem = seed_problem
            if seed_result.status == STATUS_TIME_LIMITED:
                time_limited = True

        if last_status == STATUS_INVALID_PROBLEM:
            break

        remaining = time_limit_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            time_limited = True
            break
        catalog_solve_max = _catalog_solve_max_solutions(
            len(merged_solutions),
            resolved_max_solutions,
        )

        exact_result, problem = _solve_catalog(
            observation,
            catalog,
            max_solutions=catalog_solve_max,
            time_limit_seconds=remaining,
        )
        last_status = exact_result.status
        last_diagnostics = dict(exact_result.diagnostics)
        if exact_result.status == STATUS_INVALID_PROBLEM:
            break

        if exact_result.solutions:
            _merge_exact_solutions(
                merged_solutions,
                seen_signatures,
                exact_result.solutions,
                resolved_max_solutions=resolved_max_solutions,
            )
            if exact_result.status == STATUS_TIME_LIMITED:
                time_limited = True

        band_residual_2x: int | None = None
        if not exact_result.solutions and policy_step.alpha > 0:
            remaining = time_limit_seconds - (time.monotonic() - started_at)
            if remaining > 0:
                band_result, band_problem = _solve_catalog(
                    observation,
                    catalog,
                    max_solutions=policy_step.max_seeds,
                    time_limit_seconds=remaining,
                    military_score_alpha=policy_step.alpha,
                )
                problem = band_problem
                last_diagnostics = dict(band_result.diagnostics)
                if band_result.solutions:
                    band_seeds = list(band_result.solutions[: policy_step.max_seeds])
                    best_solution = band_result.solutions[0]
                    explained = _explained_military_score_2x(best_solution, catalog)
                    band_residual_2x = observation.military_delta_2x - explained
                    if best_band_residual_2x is None or band_residual_2x < best_band_residual_2x:
                        best_band_residual_2x = band_residual_2x
                elif band_result.status == STATUS_INVALID_PROBLEM:
                    last_status = band_result.status
                    break

        step_diagnostics.append(
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

        if merged_solutions and _solution_fully_explained_by_ship_builds_only(
            merged_solutions[0],
            observation,
            catalog,
        ):
            break

        if (
            len(merged_solutions) == new_exact_before_step
            and len(merged_solutions) > 0
            and not added_combo_ids
            and not added_aggregate_action_ids
        ):
            ladder_early_stop_reason = "no_new_exact_signatures"
            break

    if catalog is None or problem is None:
        first_step = policy_steps[0]
        policy_steps_attempted.append(first_step.id)
        catalog = build_action_catalog_from_turn(
            observation,
            turn,
            policy_step=first_step,
            policy_step_index=0,
        )
        problem = build_inference_problem(observation, catalog, max_solutions=max_solutions)
        tier_result = solve_inference_problem(problem)
        last_status = tier_result.status
        last_diagnostics = dict(tier_result.diagnostics)
        _merge_exact_solutions(
            merged_solutions,
            seen_signatures,
            tier_result.solutions,
            resolved_max_solutions=resolved_max_solutions,
        )

    merged_solutions.sort(key=lambda solution: solution.objective_value, reverse=True)
    if merged_solutions:
        if any(
            _solution_satisfies_exact_hard_equalities(solution, observation, catalog)
            for solution in merged_solutions
        ):
            status = STATUS_EXACT
        elif time_limited:
            status = STATUS_TIME_LIMITED
        else:
            status = STATUS_NO_EXACT_SOLUTION
    else:
        status = STATUS_TIME_LIMITED if time_limited else last_status

    stopped_reason = ladder_early_stop_reason or last_diagnostics.get("stopped_reason", "exhausted")
    result = InferenceResult(
        status=status,
        solutions=tuple(merged_solutions),
        diagnostics={
            **last_diagnostics,
            "policy_step_id": catalog.policy_step_id,
            "policy_step_index": catalog.policy_step_index,
            "solution_count": len(merged_solutions),
            "best_band_residual_2x": best_band_residual_2x,
            "stopped_reason": stopped_reason,
        },
    )
    return result, catalog, problem, policy_steps_attempted, step_diagnostics
