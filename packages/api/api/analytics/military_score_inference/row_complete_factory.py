"""Factory for terminal RowComplete domain events."""

from __future__ import annotations

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
)
from api.analytics.military_score_inference.policy_ladder import finalize_policy_ladder_result
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.solver import STATUS_STOPPED
from api.models.game import TurnInfo


def row_complete_from_ladder_finalize(
    result: InferenceResult,
    catalog: ActionCatalog,
    problem: InferenceProblem,
    policy_steps_attempted: list[str],
    step_diagnostics: list[dict[str, object]],
) -> RowComplete:
    return RowComplete(
        result=result,
        catalog=catalog,
        problem=problem,
        policy_steps_attempted=policy_steps_attempted,
        step_diagnostics=step_diagnostics,
    )


def _row_complete_stopped_from_base(base: RowComplete) -> RowComplete:
    return RowComplete(
        result=InferenceResult(
            status=STATUS_STOPPED,
            solutions=base.result.solutions,
            diagnostics={**base.result.diagnostics, "stopped_reason": "cancelled"},
        ),
        catalog=base.catalog,
        problem=base.problem,
        policy_steps_attempted=base.policy_steps_attempted,
        step_diagnostics=base.step_diagnostics,
        force_is_complete=True,
        summary_override=base.summary_override,
        wire_observation=base.wire_observation,
        wire_turn=base.wire_turn,
        extra_diagnostics=base.extra_diagnostics,
    )


def row_complete_stopped(
    *,
    ladder_state: PolicyLadderState | None = None,
    observation: InferenceObservation | None = None,
    turn: TurnInfo | None = None,
    base: RowComplete | None = None,
) -> RowComplete:
    if base is not None:
        return _row_complete_stopped_from_base(base)
    if ladder_state is not None and ladder_state.merged_solutions:
        result, catalog, problem, policy_steps_attempted, step_diagnostics = (
            finalize_policy_ladder_result(ladder_state, observation, turn)
        )
        return _row_complete_stopped_from_base(
            row_complete_from_ladder_finalize(
                result,
                catalog,
                problem,
                policy_steps_attempted,
                step_diagnostics,
            )
        )
    return RowComplete(
        result=InferenceResult(
            status=STATUS_STOPPED,
            solutions=(),
            diagnostics={"stopped_reason": "cancelled"},
        ),
        summary_override="Build inference halted",
        force_is_complete=True,
    )
