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
from api.analytics.military_score_inference.military_sat_admission import (
    military_sat_admission_from_turn,
    military_sat_refusal_from_pairing,
)
from api.analytics.military_score_inference.military_score_window import (
    BandMilitaryScoreWindow,
    ExactMilitaryScoreWindow,
    MilitaryScoreWindow,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_admission import (
    held_leftover_0_solutions,
    make_incremental_admitter,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_budget import (
    SolveClip,
    TierStepRun,
    TierStopKind,
    ensure_ladder_clock_started,
    remaining_effort,
    remaining_time,
    tier_step_allowance,
)
from api.analytics.military_score_inference.policy_ladder_tier_finish import (
    TierStepFinishMode,
    finish_tier_step,
)
from api.analytics.military_score_inference.prior_fleet_tech_raise import (
    resolve_prior_fleet_tech_raise_plan,
)
from api.analytics.military_score_inference.ranked_solution_buffer import (
    solution_signature,
)
from api.analytics.military_score_inference.score_arithmetic import (
    catalog_explained_military_delta_2x,
)
from api.analytics.military_score_inference.search_effort import (
    INFERENCE_SEARCH_HANG_FUSE_SECONDS,
    InferenceSearchHangFuse,
)
from api.analytics.military_score_inference.ship_first_family import (
    admit_ship_first_ranked_solution,
    tag_ship_first_near_solution,
)
from api.analytics.military_score_inference.ship_first_overshoot import (
    ShipFirstOvershootPlan,
    leftover_military_2x,
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
    return catalog_explained_military_delta_2x(
        solution,
        {action.id: action for action in catalog.aggregate_actions},
        {combo.combo_id: combo for combo in catalog.ship_build_combos},
    )


def _solve_catalog(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    *,
    race_id: int | None = None,
    max_solutions: int,
    solve_clip: SolveClip,
    military_score_window: MilitaryScoreWindow | None = None,
    fixed_combo_counts: dict[str, int] | None = None,
    combo_count_neighborhood: int = 0,
    cancel_token: InferenceCancelToken | None = None,
    on_solution: Callable[[InferenceSolution], None] | None = None,
    seed_no_good_solutions: Sequence[InferenceSolution] = (),
    budget_run: TierStepRun | None = None,
) -> tuple[InferenceResult, InferenceProblem]:
    problem = build_inference_problem(
        observation,
        catalog,
        race_id=race_id,
        max_solutions=max_solutions,
        time_limit_seconds=solve_clip.problem_time_limit_seconds(),
        solve_clip=solve_clip,
        military_score_window=military_score_window,
        fixed_combo_counts=fixed_combo_counts,
        combo_count_neighborhood=combo_count_neighborhood,
    )
    result = solve_inference_problem(
        problem,
        cancel_token=cancel_token,
        on_solution=on_solution,
        seed_no_good_solutions=seed_no_good_solutions,
    )
    _charge_effort_budget(budget_run, result)
    return result, problem


def _diagnostic_float(diagnostics: dict[str, object], key: str) -> float:
    value = diagnostics.get(key, 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _charge_effort_budget(run: TierStepRun | None, result: InferenceResult) -> None:
    """Spend det time and Solve-only wall. Hang fuse fails closed after charge."""
    if run is None or not run.is_effort_budget:
        return
    diagnostics = result.diagnostics
    run.charge_search(
        deterministic_time=_diagnostic_float(diagnostics, "deterministicTime"),
        wall_seconds=_diagnostic_float(diagnostics, "solveWallSeconds"),
    )
    if diagnostics.get("hangFuseHit") or run.hang_fuse_exceeded():
        raise InferenceSearchHangFuse("inference search hang fuse exceeded; row will not persist")


def _solve_budget_kwargs(run: TierStepRun) -> dict[str, object]:
    return {"solve_clip": run.solve_clip_or_exhausted(), "budget_run": run}


def _solve_seed_progression(
    observation: InferenceObservation,
    catalog: ActionCatalog,
    seed: InferenceSolution,
    *,
    race_id: int | None = None,
    max_solutions: int,
    next_solve_clip: Callable[[], SolveClip | None],
    should_stop: Callable[[], bool] | None = None,
    cancel_token: InferenceCancelToken | None = None,
    on_solution: Callable[[InferenceSolution], None] | None = None,
    seed_no_good_solutions: Sequence[InferenceSolution] = (),
    budget_run: TierStepRun | None = None,
) -> tuple[InferenceResult | None, InferenceProblem | None]:
    """Run neighborhood then unfixed catalog solves under one shared clip.

    Each sub-solve samples ``next_solve_clip()`` at call time so successive
    passes cannot each claim the full tier allowance independently.
    """
    fixed_counts = _combo_counts_from_solution(seed)
    if not fixed_counts:
        return None, None

    def _abort() -> bool:
        if should_stop is not None and should_stop():
            return True
        return cancel_token is not None and cancel_token.is_cancelled()

    def _solve_cap() -> SolveClip | None:
        if _abort():
            return None
        clip = next_solve_clip()
        if clip is None or clip.is_exhausted():
            return None
        return clip

    for neighborhood in (0, 1):
        clip = _solve_cap()
        if clip is None:
            return None, None
        result, problem = _solve_catalog(
            observation,
            catalog,
            race_id=race_id,
            max_solutions=max_solutions,
            solve_clip=clip,
            fixed_combo_counts=fixed_counts,
            combo_count_neighborhood=neighborhood,
            cancel_token=cancel_token,
            on_solution=on_solution,
            seed_no_good_solutions=seed_no_good_solutions,
            budget_run=budget_run,
        )
        if result.status == STATUS_STOPPED:
            return result, problem
        if result.solutions:
            return result, problem

    clip = _solve_cap()
    if clip is None:
        return None, None

    result, problem = _solve_catalog(
        observation,
        catalog,
        race_id=race_id,
        max_solutions=max_solutions,
        solve_clip=clip,
        cancel_token=cancel_token,
        on_solution=on_solution,
        budget_run=budget_run,
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
    search_effort_allowance: float | None = None,
    hang_fuse_seconds: float | None = None,
) -> None:
    """Run one inference search tier step; mutates ``state`` in place.

    Stream callers pass ``search_effort_allowance``. Remaining effort is the
    allowance minus deterministic time already spent, so queue wait between
    continues does not shrink it. Wall clock is only ``hang_fuse_seconds``.

    Batch callers pass ``time_limit_seconds`` and leave the effort allowance
    unset. That path still clips each Solve on remaining case wall time.

    Ship-build combos, prior-weight tables, and the ship-transfer fragment come
    from ``state.catalog_reuse`` when this rung's inputs match or only widen.
    Each rung still receives its own action catalog.
    """
    if state.ladder_complete or state.next_step_index >= len(state.policy_steps):
        state.ladder_complete = True
        return

    if state.catalog is None:
        admission, pairing, idle_dock = military_sat_admission_from_turn(
            observation,
            turn,
            state.prior_fleet_records,
        )
        state.sat_admission = admission
        state.scoreboard_pairing = pairing
        if not admission.admitted:
            refusal = military_sat_refusal_from_pairing(
                observation,
                pairing,
                idle_dock,
                turn,
                state.prior_fleet_records,
            )
            state.refused_result = refusal
            state.last_status = refusal.status
            state.last_diagnostics = dict(refusal.diagnostics)
            state.ladder_complete = True
            return

    step_index = state.next_step_index
    policy_step = state.policy_steps[step_index]
    if search_effort_allowance is not None:
        fuse_seconds = (
            INFERENCE_SEARCH_HANG_FUSE_SECONDS if hang_fuse_seconds is None else hang_fuse_seconds
        )
        global_remaining = remaining_effort(search_effort_allowance, state.search_effort_spent)
        allowance, reserved, spendable = tier_step_allowance(
            state.policy_steps,
            step_index,
            global_remaining_effort=global_remaining,
        )
        run = TierStepRun.for_effort(
            state,
            cancel_token=cancel_token,
            allowance=allowance,
            reserved_for_later=reserved,
            spendable=spendable,
            row_effort_allowance=search_effort_allowance,
            hang_fuse_seconds=fuse_seconds,
            budget_started_at=state.search_wall_seconds,
        )
    else:
        budget_started_at = ensure_ladder_clock_started(state)
        global_remaining = remaining_time(budget_started_at, time_limit_seconds)
        allowance = global_remaining
        reserved = 0.0
        spendable = max(0.0, global_remaining)
        tier_started_at = time.monotonic()
        run = TierStepRun.for_wall(
            state,
            time_limit_seconds=time_limit_seconds,
            cancel_token=cancel_token,
            budget_started_at=budget_started_at,
            allowance_seconds=allowance,
            tier_started_at=tier_started_at,
            reserved_for_later=reserved,
            spendable=spendable,
        )
    tier_started_at = time.monotonic()
    entry_stop = run.peek_stop()
    if entry_stop is not None:
        # Zero tier allowance (min=0 and nothing spendable), or cancel before work.
        run.commit_stop(entry_stop)
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
            finish_mode=(
                TierStepFinishMode.BUDGET_STOP
                if entry_stop is TierStopKind.TIER_TIME
                else TierStepFinishMode.DIAGNOSTICS_ONLY
            ),
            tier_allowance_effort=allowance,
            reserved_for_later_effort=reserved,
            spendable_effort=spendable,
        )
        return

    state.policy_steps_attempted.append(policy_step.id)
    step_started_at = tier_started_at
    held_count_before = len(state.merged_solutions)
    newly_admitted: list[InferenceSolution] = []
    budget_kwargs = {
        "tier_allowance_effort": allowance,
        "reserved_for_later_effort": reserved,
        "spendable_effort": spendable,
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
        prior_fleet_records=state.prior_fleet_records,
        catalog_reuse=state.catalog_reuse,
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
    overlay = state.ship_first_overshoot
    overlay_mode = overlay.mode if overlay is not None else "off"
    skip_leftover_0 = overlay_mode == "overshoot_only"
    seeds_for_step = [] if overlay_mode != "off" else list(state.band_seeds)
    state.band_seeds = []

    def budget_exhausted() -> bool:
        return run.peek_stop() is not None

    if policy_step.run_degrade_aggregate_probe and state.merged_solutions and not skip_leftover_0:
        for rewrite in probe_degrade_aggregate_rewrites(
            state.merged_solutions,
            turn=turn,
            observation=observation,
            catalog=catalog,
            max_solutions=catalog_solve_max,
            should_stop=budget_exhausted,
            search_budget=run,
        ):
            if budget_exhausted():
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

    def stop_after_budget() -> bool:
        stop = run.peek_stop()
        if stop is None:
            return False
        run.commit_stop(stop)
        if run.is_tier_only_stop():
            finish_step(finish_mode=TierStepFinishMode.BUDGET_STOP)
        else:
            finish_step()
        return True

    def record_solve(
        result: InferenceResult,
        problem: InferenceProblem,
    ) -> bool:
        """Apply solve outcome. Return True when the tier should abort."""
        state.last_status = result.status
        state.last_diagnostics = dict(result.diagnostics)
        state.problem = problem
        if result.status == STATUS_INVALID_PROBLEM:
            finish_step()
            state.ladder_complete = True
            return True
        if result.status == STATUS_STOPPED:
            state.cancelled = True
            finish_step()
            state.ladder_complete = True
            return True
        if result.status == STATUS_TIME_LIMITED:
            state.time_limited = True
        return False

    def admit_overshoot(solution: InferenceSolution) -> None:
        tagged = tag_ship_first_near_solution(solution, observation, catalog)
        admitted = admit_ship_first_ranked_solution(
            state.merged_solutions,
            state.seen_signatures,
            tagged,
            max_solutions=state.resolved_max_solutions,
            leftover_2x=lambda held: leftover_military_2x(held, observation, catalog),
            on_admitted=None,
        )
        if admitted:
            newly_admitted.append(tagged)
            state.overshoot_signatures.add(solution_signature(tagged))

    for seed in seeds_for_step[: policy_step.max_seeds]:
        if stop_after_budget():
            return
        seed_result, seed_problem = _solve_seed_progression(
            observation,
            catalog,
            seed,
            race_id=player_race_id,
            max_solutions=catalog_solve_max,
            next_solve_clip=run.next_solve_clip,
            should_stop=budget_exhausted,
            cancel_token=cancel_token,
            on_solution=admit_solution,
            seed_no_good_solutions=held_no_goods,
            budget_run=run,
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

    if stop_after_budget():
        return

    held_no_goods = tuple(state.merged_solutions)
    band_residual_2x: int | None = None

    def _solve_overshoot_catalog(plan: ShipFirstOvershootPlan) -> bool:
        overshoot_result, overshoot_problem = _solve_catalog(
            observation,
            catalog,
            race_id=player_race_id,
            max_solutions=catalog_solve_max,
            **_solve_budget_kwargs(run),
            military_score_window=plan.overshoot_window(),
            cancel_token=cancel_token,
            on_solution=admit_overshoot,
            seed_no_good_solutions=tuple(state.merged_solutions),
        )
        return record_solve(overshoot_result, overshoot_problem)

    def _solve_military_window() -> bool:
        """Exact, overshoot, or band for this step. True aborts the tier."""
        nonlocal band_residual_2x
        if overlay_mode == "overshoot_only" and overlay is not None:
            if (
                overlay.should_solve_overshoot
                and not budget_exhausted()
                and run.remaining_allowance() > 0
            ):
                return _solve_overshoot_catalog(overlay)
            clip = run.solve_clip_or_exhausted()
            state.problem = build_inference_problem(
                observation,
                catalog,
                race_id=player_race_id,
                max_solutions=catalog_solve_max,
                time_limit_seconds=clip.problem_time_limit_seconds(),
                solve_clip=clip,
                military_score_window=overlay.overshoot_window(),
            )
            return False

        exact_result, problem = _solve_catalog(
            observation,
            catalog,
            race_id=player_race_id,
            max_solutions=catalog_solve_max,
            **_solve_budget_kwargs(run),
            military_score_window=ExactMilitaryScoreWindow(),
            cancel_token=cancel_token,
            on_solution=admit_solution,
            seed_no_good_solutions=held_no_goods,
        )
        if record_solve(exact_result, problem):
            return True

        if overlay_mode == "exact_then_overshoot" and overlay is not None:
            held_exact = held_leftover_0_solutions(state, observation, catalog)
            if (
                overlay.should_solve_overshoot
                and not held_exact
                and not budget_exhausted()
                and run.remaining_allowance() > 0
            ):
                return _solve_overshoot_catalog(overlay)
            return False

        if exact_result.solutions or policy_step.alpha <= 0:
            return False
        if budget_exhausted() or run.remaining_allowance() <= 0:
            return False
        band_result, band_problem = _solve_catalog(
            observation,
            catalog,
            race_id=player_race_id,
            max_solutions=policy_step.max_seeds,
            **_solve_budget_kwargs(run),
            military_score_window=BandMilitaryScoreWindow(alpha=policy_step.alpha),
            cancel_token=cancel_token,
            seed_no_good_solutions=tuple(state.merged_solutions),
        )
        state.problem = band_problem
        state.last_diagnostics = dict(band_result.diagnostics)
        if band_result.status == STATUS_STOPPED:
            state.cancelled = True
            finish_step()
            state.ladder_complete = True
            return True
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
            return True
        return False

    if _solve_military_window():
        return

    finish_step(
        finish_mode=TierStepFinishMode.COMPLETE,
        band_residual_2x=band_residual_2x,
        added_combo_ids=added_combo_ids,
        added_aggregate_action_ids=added_aggregate_action_ids,
        new_exact_before_step=new_exact_before_step,
    )
