"""YAML tier policy ladder execution: walk steps, seed carry-forward, merge solutions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from api.analytics.fleet.types import FleetShipRecord
from api.analytics.military_score_inference.actions import (
    DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    ActionCatalog,
)
from api.analytics.military_score_inference.fleet_torp_overlay import FleetTorpOverlay
from api.analytics.military_score_inference.hopeless_classifier import (
    HopelessRowFacts,
    hopeless_context_for_row,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_admission import leftover_0_solutions
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.ship_first_overshoot import (
    SHIP_FIRST_PREFIX_STOP_REASON,
    leftover_military_2x,
    resolve_ship_first_overshoot_plan,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.military_score_inference.worthwhile_remainder_bound import (
    worthwhile_remainder_bound_diagnostics,
    worthwhile_remainder_bound_for_turn,
)
from api.models.game import TurnInfo


def _missing_tier_state_result(
    state: PolicyLadderState,
    merged_solutions: list[InferenceSolution],
) -> InferenceResult:
    """Build a terminal result when finalize runs without tier catalog/problem state."""
    if state.cancelled:
        status = STATUS_STOPPED
        stopped_reason = "cancelled"
    elif state.time_limited:
        status = STATUS_TIME_LIMITED
        stopped_reason = state.ladder_early_stop_reason or state.last_diagnostics.get(
            "stopped_reason",
            "exhausted",
        )
    elif not state.policy_steps:
        status = STATUS_INVALID_PROBLEM
        stopped_reason = "empty_policy_ladder"
    else:
        status = STATUS_INVALID_PROBLEM
        stopped_reason = "policy_ladder_finalize_without_tier_state"

    diagnostics: dict[str, object] = {
        **state.last_diagnostics,
        "solution_count": len(merged_solutions),
        "best_band_residual_2x": state.best_band_residual_2x,
        "stopped_reason": stopped_reason,
    }
    if status == STATUS_INVALID_PROBLEM:
        diagnostics["reason"] = stopped_reason

    return InferenceResult(
        status=status,
        solutions=tuple(merged_solutions),
        diagnostics=diagnostics,
    )


def finalize_policy_ladder_result(
    state: PolicyLadderState,
    observation: InferenceObservation,
    turn: TurnInfo,
    *,
    max_solutions: int | None = None,
) -> tuple[
    InferenceResult,
    ActionCatalog | None,
    InferenceProblem | None,
    list[str],
    list[dict[str, object]],
]:
    """Build the terminal inference result from ladder state."""
    catalog = state.catalog
    problem = state.problem
    merged_solutions = list(state.merged_solutions)

    if catalog is None or problem is None:
        return (
            _missing_tier_state_result(state, merged_solutions),
            None,
            None,
            state.policy_steps_attempted,
            state.step_diagnostics,
        )
    plan = state.ship_first_overshoot
    skip_leftover_0 = plan is not None and plan.skip_leftover_0_exact
    leftover_0 = leftover_0_solutions(
        merged_solutions,
        observation,
        catalog,
        overshoot_signatures=state.overshoot_signatures,
    )
    if leftover_0 and not skip_leftover_0:
        merged_solutions = leftover_0
    if plan is not None and plan.active:
        merged_solutions.sort(
            key=lambda solution: (
                -solution.objective_value,
                leftover_military_2x(solution, observation, catalog),
            )
        )
    else:
        merged_solutions.sort(key=lambda solution: solution.objective_value, reverse=True)

    prefix_residual = state.ladder_early_stop_reason in (
        "expensive_tier_abort",
        SHIP_FIRST_PREFIX_STOP_REASON,
    )
    if state.cancelled:
        status = STATUS_STOPPED
    elif leftover_0 and not skip_leftover_0:
        status = STATUS_EXACT
    elif skip_leftover_0:
        status = STATUS_MINE_SCORE_RESIDUAL
    elif merged_solutions:
        if plan is not None and plan.active:
            status = STATUS_MINE_SCORE_RESIDUAL
        elif prefix_residual:
            status = state.last_status if state.last_status else STATUS_MINE_SCORE_RESIDUAL
        elif state.time_limited:
            status = STATUS_TIME_LIMITED
        else:
            status = STATUS_NO_EXACT_SOLUTION
    elif plan is not None and plan.active:
        status = STATUS_MINE_SCORE_RESIDUAL
    else:
        status = STATUS_TIME_LIMITED if state.time_limited else state.last_status

    stopped_reason = state.ladder_early_stop_reason or state.last_diagnostics.get(
        "stopped_reason",
        "exhausted",
    )
    if state.cancelled:
        stopped_reason = "cancelled"
    diagnostics: dict[str, object] = {
        **state.last_diagnostics,
        "policy_step_id": catalog.policy_step_id,
        "policy_step_index": catalog.policy_step_index,
        "solution_count": len(merged_solutions),
        "best_band_residual_2x": state.best_band_residual_2x,
        "stopped_reason": stopped_reason,
    }
    bound = worthwhile_remainder_bound_for_turn(observation, turn)
    if bound is not None:
        diagnostics.update(worthwhile_remainder_bound_diagnostics(bound))
    result = InferenceResult(
        status=status,
        solutions=tuple(merged_solutions),
        diagnostics=diagnostics,
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
    time_limit_seconds: float | None = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    cancel_token: InferenceCancelToken | None = None,
    on_admitted: Callable[[InferenceSolution], None] | None = None,
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
    prior_fleet_max_tech_by_axis: dict[str, int] | None = None,
    prior_fleet_records: tuple[FleetShipRecord, ...] = (),
    hopeless_context: HopelessRowFacts | None = None,
) -> tuple[
    InferenceResult,
    ActionCatalog | None,
    InferenceProblem | None,
    list[str],
    list[dict[str, object]],
]:
    """Walk the YAML inference search tier ladder with band seed carry-forward.

    Soft-global wall time **steers** per-step allowances (via
    ``tier_step_allowance_seconds`` inside each tier step). It must not hard-stop
    the batch loop: later steps with ``min_seconds > 0`` still dispatch their
    absolute floor even when soft-global remainder is already <= 0. Steps with
    ``min_seconds == 0`` and zero spendable skip inside the tier step.
    """
    resolved_max_solutions = max_solutions if max_solutions is not None else 20
    resolved_hopeless = hopeless_context
    if resolved_hopeless is None:
        resolved_hopeless = hopeless_context_for_row(observation, turn, policy_path=policy_path)
    state = PolicyLadderState(
        policy_steps=tuple(resolve_tier_policies(policy_path)),
        resolved_max_solutions=resolved_max_solutions,
        resolved_mask=resolved_mask,
        fleet_torp_overlay=fleet_torp_overlay,
        prior_fleet_max_tech_by_axis=prior_fleet_max_tech_by_axis,
        prior_fleet_records=prior_fleet_records,
        hopeless_context=resolved_hopeless,
        ship_first_overshoot=resolve_ship_first_overshoot_plan(
            observation,
            turn,
            hopeless_context=resolved_hopeless,
        ),
    )
    while not state.ladder_complete and state.next_step_index < len(state.policy_steps):
        if cancel_token is not None and cancel_token.is_cancelled():
            state.cancelled = True
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
