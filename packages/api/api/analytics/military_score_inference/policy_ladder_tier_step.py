"""Single-tier execution for the YAML inference search policy ladder."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.collision_hull_widen import (
    CollisionHullWidenPlan,
    load_twins_for_turn,
    resolve_collision_hull_widen_plan,
)
from api.analytics.military_score_inference.component_eligibility import (
    player_by_id,
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.constraints import (
    solution_satisfies_exact_hard_equalities,
)
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.prior_fleet_tech_raise import (
    PriorFleetTechRaisePlan,
    resolve_prior_fleet_tech_raise_plan,
)
from api.analytics.military_score_inference.solver import (
    STATUS_INVALID_PROBLEM,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
    solution_signature,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import (
    InferenceTierPolicyStep,
    resolve_solver_thresholds,
)
from api.models.game import TurnInfo


def remaining_time(started_at: float, time_limit_seconds: float | None) -> float:
    if time_limit_seconds is None:
        return float("inf")
    return time_limit_seconds - (time.monotonic() - started_at)


def _combo_counts_from_solution(solution: InferenceSolution) -> dict[str, int]:
    return {ship_build.combo_id: ship_build.count for ship_build in solution.ship_builds}


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
    race_id: int | None = None,
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
        race_id=race_id,
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
    race_id: int | None = None,
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
            race_id=race_id,
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
        race_id=race_id,
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
    catalog: ActionCatalog | None,
    turn: TurnInfo,
    observation: InferenceObservation,
    seed_count: int,
    band_residual_2x: int | None,
    collision_widen: CollisionHullWidenPlan | None = None,
    prior_fleet_tech_raise: PriorFleetTechRaisePlan | None = None,
) -> dict[str, object]:
    catalog_context = turn_catalog_context_for_policy_step(
        turn,
        observation.player_id,
        policy_step,
    )
    diagnostics: dict[str, object] = {
        "policyStepId": policy_step.id,
        "policyStepIndex": policy_step_index,
        "policyStepsAttempted": policy_step_index + 1,
        "constraintSnapshot": policy_step.constraint_snapshot(),
        "resolvedEligibleEngineIds": sorted(catalog_context.eligible_engine_ids),
        "resolvedEligibleBeamIds": sorted(catalog_context.eligible_beam_ids),
        "resolvedEligibleTorpIds": sorted(catalog_context.eligible_torp_ids),
        "resolvedBuildableHullIds": sorted(catalog_context.buildable_hull_ids),
        "alpha": policy_step.alpha,
        "comboCount": len(catalog.ship_build_combos) if catalog is not None else 0,
        "seedCount": seed_count,
        "bandResidual2x": band_residual_2x,
        "allowShipOnlyExactEarlyStop": policy_step.allow_ship_only_exact_early_stop,
        "hullCollisionTwinWiden": policy_step.hull_collision_twin_widen,
    }
    if collision_widen is not None:
        diagnostics.update(collision_widen.to_diagnostics())
    if prior_fleet_tech_raise is not None:
        diagnostics.update(prior_fleet_tech_raise.to_diagnostics())
    return diagnostics


def _ensure_hull_collision_twins_loaded(state: PolicyLadderState, turn: TurnInfo) -> None:
    if state.hull_collision_twins_loaded:
        return
    asset, path, fell_back = load_twins_for_turn(turn)
    state.hull_collision_twins = asset
    state.hull_collision_twins_path = str(path) if path is not None else None
    state.hull_collision_twins_fell_back = fell_back
    state.hull_collision_twins_loaded = True


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


def _finish_skipped_policy_step(
    state: PolicyLadderState,
    *,
    policy_step: InferenceTierPolicyStep,
    policy_step_index: int,
    turn: TurnInfo,
    observation: InferenceObservation,
    seed_count: int,
    collision_widen: CollisionHullWidenPlan | None = None,
    prior_fleet_tech_raise: PriorFleetTechRaisePlan | None = None,
) -> None:
    state.step_diagnostics.append(
        _policy_step_diagnostics(
            policy_step=policy_step,
            policy_step_index=policy_step_index,
            catalog=state.catalog,
            turn=turn,
            observation=observation,
            seed_count=seed_count,
            band_residual_2x=None,
            collision_widen=collision_widen,
            prior_fleet_tech_raise=prior_fleet_tech_raise,
        )
    )
    state.next_step_index = policy_step_index + 1
    if _maybe_early_stop_after_step(
        state,
        policy_step=policy_step,
        observation=observation,
        catalog=state.catalog,
    ):
        return
    if state.next_step_index >= len(state.policy_steps):
        state.ladder_complete = True


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


@dataclass
class _TierStepRun:
    """Cancel and time-budget guards shared across one tier step."""

    state: PolicyLadderState
    time_limit_seconds: float | None
    cancel_token: InferenceCancelToken | None

    def should_stop(self) -> bool:
        if self.cancel_token is not None and self.cancel_token.is_cancelled():
            self.state.cancelled = True
            self.state.ladder_complete = True
            return True
        if remaining_time(self.state.started_at, self.time_limit_seconds) <= 0:
            self.state.time_limited = True
            self.state.ladder_complete = True
            return True
        return False

    def remaining_seconds(self) -> float:
        return remaining_time(self.state.started_at, self.time_limit_seconds)


def _abort_tier_step_on_seed_result(
    state: PolicyLadderState,
    seed_result: InferenceResult,
    seed_problem: InferenceProblem,
) -> bool:
    """Apply terminal seed status to state. Returns True when the tier step should end."""
    if seed_result.status == STATUS_INVALID_PROBLEM:
        state.last_status = seed_result.status
        state.last_diagnostics = dict(seed_result.diagnostics)
        state.problem = seed_problem
        state.ladder_complete = True
        return True
    if seed_result.status == STATUS_STOPPED:
        state.cancelled = True
        state.last_status = seed_result.status
        state.last_diagnostics = dict(seed_result.diagnostics)
        state.problem = seed_problem
        state.ladder_complete = True
        return True
    return False


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

    run = _TierStepRun(state, time_limit_seconds, cancel_token)
    if run.should_stop():
        return

    step_index = state.next_step_index
    policy_step = state.policy_steps[step_index]
    state.policy_steps_attempted.append(policy_step.id)
    collision_widen: CollisionHullWidenPlan | None = None
    if policy_step.hull_collision_twin_widen:
        _ensure_hull_collision_twins_loaded(state, turn)
        collision_widen = resolve_collision_hull_widen_plan(
            policy_step,
            observation=observation,
            turn=turn,
            merged_solutions=state.merged_solutions,
            prior_catalog=state.catalog,
            resolved_mask=state.resolved_mask,
            twins_asset=state.hull_collision_twins,
            twins_asset_path=(
                Path(state.hull_collision_twins_path)
                if state.hull_collision_twins_path is not None
                else None
            ),
            twins_fell_back=state.hull_collision_twins_fell_back,
        )
        if collision_widen.skipped:
            _finish_skipped_policy_step(
                state,
                policy_step=policy_step,
                policy_step_index=step_index,
                turn=turn,
                observation=observation,
                seed_count=len(state.band_seeds),
                collision_widen=collision_widen,
            )
            return
        policy_step = collision_widen.policy_step

    prior_fleet_tech_raise = resolve_prior_fleet_tech_raise_plan(
        policy_step,
        turn=turn,
        prior_fleet_max_tech_by_axis=state.prior_fleet_max_tech_by_axis,
    )
    if prior_fleet_tech_raise is not None:
        if prior_fleet_tech_raise.skipped:
            _finish_skipped_policy_step(
                state,
                policy_step=prior_fleet_tech_raise.policy_step,
                policy_step_index=step_index,
                turn=turn,
                observation=observation,
                seed_count=len(state.band_seeds),
                collision_widen=collision_widen,
                prior_fleet_tech_raise=prior_fleet_tech_raise,
            )
            return
        policy_step = prior_fleet_tech_raise.policy_step

    player_race_id = player_by_id(turn, observation.player_id).raceid
    catalog = build_action_catalog_from_turn(
        observation,
        turn,
        policy_step=policy_step,
        policy_step_index=step_index,
        resolved_mask=state.resolved_mask,
        fleet_torp_overlay=state.fleet_torp_overlay,
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

    admit_solution = _make_incremental_admitter(state, on_admitted)
    catalog_solve_max = _catalog_solve_max_solutions(
        len(state.merged_solutions),
        state.resolved_max_solutions,
    )

    new_exact_before_step = len(state.merged_solutions)
    seeds_for_step = list(state.band_seeds)
    state.band_seeds = []

    for seed in seeds_for_step[: policy_step.max_seeds]:
        if run.should_stop():
            return
        seed_result, seed_problem = _solve_seed_progression(
            observation,
            catalog,
            seed,
            race_id=player_race_id,
            max_solutions=catalog_solve_max,
            time_limit_seconds=run.remaining_seconds(),
            cancel_token=cancel_token,
            on_solution=admit_solution,
        )
        if seed_result is None or seed_problem is None:
            continue
        if _abort_tier_step_on_seed_result(state, seed_result, seed_problem):
            return
        state.problem = seed_problem
        if seed_result.status == STATUS_TIME_LIMITED:
            state.time_limited = True

    if state.last_status == STATUS_INVALID_PROBLEM:
        state.ladder_complete = True
        return

    if run.should_stop():
        return

    catalog_solve_max = _catalog_solve_max_solutions(
        len(state.merged_solutions),
        state.resolved_max_solutions,
    )

    exact_result, problem = _solve_catalog(
        observation,
        catalog,
        race_id=player_race_id,
        max_solutions=catalog_solve_max,
        time_limit_seconds=run.remaining_seconds(),
        cancel_token=cancel_token,
        on_solution=admit_solution,
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

    if exact_result.status == STATUS_TIME_LIMITED:
        state.time_limited = True

    band_residual_2x: int | None = None
    if not exact_result.solutions and policy_step.alpha > 0:
        if not run.should_stop() and run.remaining_seconds() > 0:
            band_result, band_problem = _solve_catalog(
                observation,
                catalog,
                race_id=player_race_id,
                max_solutions=policy_step.max_seeds,
                time_limit_seconds=run.remaining_seconds(),
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
            collision_widen=collision_widen,
            prior_fleet_tech_raise=prior_fleet_tech_raise,
        )
    )

    state.next_step_index = step_index + 1

    if _maybe_early_stop_after_step(
        state,
        policy_step=policy_step,
        observation=observation,
        catalog=catalog,
    ):
        return

    if _maybe_no_new_exact_signatures_early_stop(
        state,
        added_combo_ids=added_combo_ids,
        added_aggregate_action_ids=added_aggregate_action_ids,
        new_exact_before_step=new_exact_before_step,
    ):
        return

    if state.next_step_index >= len(state.policy_steps):
        state.ladder_complete = True
