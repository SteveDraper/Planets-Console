"""Single-tier execution for the YAML inference search policy ladder."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
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
)
from api.analytics.military_score_inference.degrade_aggregate_probe import (
    probe_degrade_aggregate_rewrites,
)
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_admission import (
    make_incremental_admitter,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_budget import (
    TierStepRun,
    ensure_ladder_clock_started,
    remaining_time,
    tier_step_allowance_seconds,
)
from api.analytics.military_score_inference.policy_ladder_tier_finish import (
    TierStepFinishMode,
    finish_tier_step,
)
from api.analytics.military_score_inference.prior_fleet_tech_raise import (
    resolve_prior_fleet_tech_raise_plan,
)
from api.analytics.military_score_inference.solver import (
    STATUS_INVALID_PROBLEM,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
    solve_inference_problem,
)
from api.models.game import TurnInfo


def _combo_counts_from_solution(solution: InferenceSolution) -> dict[str, int]:
    return {ship_build.combo_id: ship_build.count for ship_build in solution.ship_builds}


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
    seed_no_good_solutions: Sequence[InferenceSolution] = (),
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
            seed_no_good_solutions=seed_no_good_solutions,
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
    remaining_seconds: Callable[[], float],
    should_stop: Callable[[], bool] | None = None,
    cancel_token: InferenceCancelToken | None = None,
    on_solution: Callable[[InferenceSolution], None] | None = None,
    seed_no_good_solutions: Sequence[InferenceSolution] = (),
) -> tuple[InferenceResult | None, InferenceProblem | None]:
    """Run neighborhood then unfixed catalog solves under one shared wall.

    Each sub-solve samples ``remaining_seconds()`` at call time so successive
    passes cannot each claim the full tier allowance independently.
    """
    fixed_counts = _combo_counts_from_solution(seed)
    if not fixed_counts:
        return None, None

    def _abort() -> bool:
        if should_stop is not None and should_stop():
            return True
        return cancel_token is not None and cancel_token.is_cancelled()

    def _solve_cap() -> float | None:
        if _abort():
            return None
        limit = remaining_seconds()
        if limit <= 0:
            return None
        return limit

    for neighborhood in (0, 1):
        limit = _solve_cap()
        if limit is None:
            return None, None
        result, problem = _solve_catalog(
            observation,
            catalog,
            race_id=race_id,
            max_solutions=max_solutions,
            time_limit_seconds=limit,
            fixed_combo_counts=fixed_counts,
            combo_count_neighborhood=neighborhood,
            cancel_token=cancel_token,
            on_solution=on_solution,
            seed_no_good_solutions=seed_no_good_solutions,
        )
        if result.status == STATUS_STOPPED:
            return result, problem
        if result.solutions:
            return result, problem

    limit = _solve_cap()
    if limit is None:
        return None, None

    result, problem = _solve_catalog(
        observation,
        catalog,
        race_id=race_id,
        max_solutions=max_solutions,
        time_limit_seconds=limit,
        cancel_token=cancel_token,
        on_solution=on_solution,
        seed_no_good_solutions=seed_no_good_solutions,
    )
    if result.solutions or result.status == STATUS_STOPPED:
        return result, problem
    return None, None


def _ensure_hull_collision_twins_loaded(state: PolicyLadderState, turn: TurnInfo) -> None:
    if state.hull_collision_twins_loaded:
        return
    asset, path, fell_back = load_twins_for_turn(turn)
    state.hull_collision_twins = asset
    state.hull_collision_twins_path = str(path) if path is not None else None
    state.hull_collision_twins_fell_back = fell_back
    state.hull_collision_twins_loaded = True


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
    """Run one inference search tier step; mutates ``state`` in place.

    The wall budget is shared across continues and anchored at first dispatch
    (``state.started_at``), so SPA rows that sat in ``waiting_deps`` do not
    instantly ``time_limited``, and multi-tier climbs do not get a fresh full
    limit on every step.
    """
    if state.ladder_complete or state.next_step_index >= len(state.policy_steps):
        state.ladder_complete = True
        return

    ladder_started_at = ensure_ladder_clock_started(state)
    step_index = state.next_step_index
    policy_step = state.policy_steps[step_index]
    global_remaining = remaining_time(ladder_started_at, time_limit_seconds)
    allowance, reserved, spendable = tier_step_allowance_seconds(
        state.policy_steps,
        step_index,
        global_remaining_seconds=global_remaining,
    )
    tier_started_at = time.monotonic()
    run = TierStepRun(
        state,
        time_limit_seconds,
        cancel_token,
        budget_started_at=ladder_started_at,
        tier_allowance_seconds=allowance,
        tier_started_at=tier_started_at,
        reserved_for_later_seconds=reserved,
        spendable_seconds=spendable,
    )
    if run.should_stop():
        # Zero tier allowance (min=0 and nothing spendable), or cancel.
        if run.is_tier_only_stop():
            state.policy_steps_attempted.append(policy_step.id)
            finish_tier_step(
                state,
                policy_step=policy_step,
                policy_step_index=step_index,
                catalog=state.catalog,
                turn=turn,
                observation=observation,
                seed_count=len(state.band_seeds),
                band_residual_2x=None,
                step_started_at=tier_started_at,
                held_count_before=len(state.merged_solutions),
                newly_admitted=[],
                skipped=True,
                finish_mode=TierStepFinishMode.BUDGET_STOP,
                tier_allowance_seconds=allowance,
                reserved_for_later_seconds=reserved,
                spendable_seconds=spendable,
            )
        return

    state.policy_steps_attempted.append(policy_step.id)
    step_started_at = tier_started_at
    held_count_before = len(state.merged_solutions)
    newly_admitted: list[InferenceSolution] = []
    budget_kwargs = {
        "tier_allowance_seconds": allowance,
        "reserved_for_later_seconds": reserved,
        "spendable_seconds": spendable,
    }

    def track_admitted(solution: InferenceSolution) -> None:
        newly_admitted.append(solution)
        if on_admitted is not None:
            on_admitted(solution)

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
            finish_tier_step(
                state,
                policy_step=policy_step,
                policy_step_index=step_index,
                catalog=state.catalog,
                turn=turn,
                observation=observation,
                seed_count=len(state.band_seeds),
                band_residual_2x=None,
                step_started_at=step_started_at,
                held_count_before=held_count_before,
                newly_admitted=newly_admitted,
                collision_widen=collision_widen,
                skipped=True,
                finish_mode=TierStepFinishMode.SKIP,
                **budget_kwargs,
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
            finish_tier_step(
                state,
                policy_step=prior_fleet_tech_raise.policy_step,
                policy_step_index=step_index,
                catalog=state.catalog,
                turn=turn,
                observation=observation,
                seed_count=len(state.band_seeds),
                band_residual_2x=None,
                step_started_at=step_started_at,
                held_count_before=held_count_before,
                newly_admitted=newly_admitted,
                collision_widen=collision_widen,
                prior_fleet_tech_raise=prior_fleet_tech_raise,
                skipped=True,
                finish_mode=TierStepFinishMode.SKIP,
                **budget_kwargs,
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

    admit_solution = make_incremental_admitter(state, track_admitted)
    catalog_solve_max = state.resolved_max_solutions
    held_no_goods: tuple[InferenceSolution, ...] = tuple(state.merged_solutions)

    new_exact_before_step = len(state.merged_solutions)
    seeds_for_step = list(state.band_seeds)
    state.band_seeds = []

    if policy_step.run_degrade_aggregate_probe and state.merged_solutions:
        for rewrite in probe_degrade_aggregate_rewrites(
            state.merged_solutions,
            turn=turn,
            observation=observation,
            catalog=catalog,
            max_solutions=catalog_solve_max,
            should_stop=run.should_stop,
            remaining_seconds=run.remaining_seconds,
        ):
            if run.should_stop():
                break
            admit_solution(rewrite)

    def finish_step(
        *,
        finish_mode: TierStepFinishMode = TierStepFinishMode.DIAGNOSTICS_ONLY,
        band_residual_2x: int | None = None,
        added_combo_ids: frozenset[str] = frozenset(),
        added_aggregate_action_ids: frozenset[str] = frozenset(),
        new_exact_before_step: int | None = None,
    ) -> None:
        finish_tier_step(
            state,
            policy_step=policy_step,
            policy_step_index=step_index,
            catalog=catalog,
            turn=turn,
            observation=observation,
            seed_count=len(seeds_for_step),
            band_residual_2x=band_residual_2x,
            step_started_at=step_started_at,
            held_count_before=held_count_before,
            newly_admitted=newly_admitted,
            collision_widen=collision_widen,
            prior_fleet_tech_raise=prior_fleet_tech_raise,
            finish_mode=finish_mode,
            added_combo_ids=added_combo_ids,
            added_aggregate_action_ids=added_aggregate_action_ids,
            new_exact_before_step=new_exact_before_step,
            **budget_kwargs,
        )

    def stop_after_budget() -> None:
        if run.is_tier_only_stop():
            finish_step(finish_mode=TierStepFinishMode.BUDGET_STOP)
        else:
            finish_step()

    for seed in seeds_for_step[: policy_step.max_seeds]:
        if run.should_stop():
            stop_after_budget()
            return
        seed_result, seed_problem = _solve_seed_progression(
            observation,
            catalog,
            seed,
            race_id=player_race_id,
            max_solutions=catalog_solve_max,
            remaining_seconds=run.remaining_seconds,
            should_stop=run.should_stop,
            cancel_token=cancel_token,
            on_solution=admit_solution,
            seed_no_good_solutions=held_no_goods,
        )
        if seed_result is None or seed_problem is None:
            continue
        if _abort_tier_step_on_seed_result(state, seed_result, seed_problem):
            finish_step()
            return
        state.problem = seed_problem
        if seed_result.status == STATUS_TIME_LIMITED:
            state.time_limited = True

    if state.last_status == STATUS_INVALID_PROBLEM:
        finish_step()
        state.ladder_complete = True
        return

    if run.should_stop():
        stop_after_budget()
        return

    # Include anything admitted during seed progression so the main catalog
    # solve does not rediscover those structures.
    held_no_goods = tuple(state.merged_solutions)
    exact_result, problem = _solve_catalog(
        observation,
        catalog,
        race_id=player_race_id,
        max_solutions=catalog_solve_max,
        time_limit_seconds=run.remaining_seconds(),
        cancel_token=cancel_token,
        on_solution=admit_solution,
        seed_no_good_solutions=held_no_goods,
    )
    state.last_status = exact_result.status
    state.last_diagnostics = dict(exact_result.diagnostics)
    state.problem = problem
    if exact_result.status == STATUS_INVALID_PROBLEM:
        finish_step()
        state.ladder_complete = True
        return
    if exact_result.status == STATUS_STOPPED:
        state.cancelled = True
        finish_step()
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
                seed_no_good_solutions=tuple(state.merged_solutions),
            )
            state.problem = band_problem
            state.last_diagnostics = dict(band_result.diagnostics)
            if band_result.status == STATUS_STOPPED:
                state.cancelled = True
                finish_step()
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
                finish_step()
                state.ladder_complete = True
                return

    finish_step(
        finish_mode=TierStepFinishMode.COMPLETE,
        band_residual_2x=band_residual_2x,
        added_combo_ids=added_combo_ids,
        added_aggregate_action_ids=added_aggregate_action_ids,
        new_exact_before_step=new_exact_before_step,
    )
