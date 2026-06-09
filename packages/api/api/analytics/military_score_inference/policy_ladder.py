"""YAML tier policy ladder execution: walk steps, seed carry-forward, merge solutions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from api.analytics.military_score_inference.actions import (
    DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    ActionCatalog,
)
from api.analytics.military_score_inference.constraints import (
    solution_satisfies_exact_hard_equalities,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    remaining_time,
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
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
    merged_solutions.sort(key=lambda solution: solution.objective_value, reverse=True)

    if state.cancelled:
        status = STATUS_STOPPED
    elif merged_solutions:
        if any(
            solution_satisfies_exact_hard_equalities(solution, observation, catalog)
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
    ActionCatalog | None,
    InferenceProblem | None,
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
        remaining = remaining_time(state.started_at, time_limit_seconds)
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
