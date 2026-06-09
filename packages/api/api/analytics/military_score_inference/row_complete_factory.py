"""Factory for terminal RowComplete domain events."""

from __future__ import annotations

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_api_payload import (
    format_inference_summary,
    inference_api_payload,
    inference_result_to_api_payload,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    RowComplete,
    RowCompleteWirePayload,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
)
from api.analytics.military_score_inference.policy_ladder import finalize_policy_ladder_result
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.solver import STATUS_STOPPED
from api.models.game import TurnInfo


def row_complete_wire_payload_from_api_payload(
    payload: dict[str, object],
    *,
    force_is_complete: bool | None = None,
) -> RowCompleteWirePayload:
    if force_is_complete is not None:
        payload = {**payload, "isComplete": force_is_complete}
    diagnostics = payload.get("diagnostics")
    wire_solutions = payload.get("solutions")
    return RowCompleteWirePayload(
        status=str(payload.get("status", "")),
        summary=str(payload.get("summary", "")),
        solution_count=int(payload.get("solutionCount", 0)),
        is_complete=bool(payload.get("isComplete", True)),
        solutions=wire_solutions if isinstance(wire_solutions, list) else [],
        diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
    )


def build_row_complete_wire_payload(
    result: InferenceResult,
    *,
    observation: InferenceObservation | None = None,
    turn: TurnInfo | None = None,
    catalog: ActionCatalog | None = None,
    problem: InferenceProblem | None = None,
    policy_steps_attempted: list[str] | None = None,
    step_diagnostics: list[dict[str, object]] | None = None,
    extra_diagnostics: dict[str, object] | None = None,
    summary_override: str | None = None,
    force_is_complete: bool | None = None,
) -> RowCompleteWirePayload:
    if catalog is not None and problem is not None:
        if observation is None or turn is None:
            raise ValueError("observation and turn are required when catalog and problem are set")
        payload = inference_result_to_api_payload(
            result,
            catalog,
            observation,
            turn,
            problem,
            policy_steps_attempted=policy_steps_attempted,
            step_diagnostics=step_diagnostics,
            extra_diagnostics=extra_diagnostics,
        )
    else:
        summary = summary_override or format_inference_summary(result)
        payload = inference_api_payload(
            status=result.status,
            summary=summary,
            solutions=result.solutions,
            diagnostics=result.diagnostics,
        )
    return row_complete_wire_payload_from_api_payload(
        payload,
        force_is_complete=force_is_complete,
    )


def row_complete_with_summary(
    result: InferenceResult,
    *,
    summary: str | None = None,
) -> RowComplete:
    return RowComplete(
        result=result,
        wire_payload=build_row_complete_wire_payload(
            result,
            summary_override=summary,
        ),
    )


def row_complete_from_ladder_finalize(
    result: InferenceResult,
    catalog: ActionCatalog,
    problem: InferenceProblem,
    policy_steps_attempted: list[str],
    step_diagnostics: list[dict[str, object]],
    *,
    observation: InferenceObservation,
    turn: TurnInfo,
    extra_diagnostics: dict[str, object] | None = None,
) -> RowComplete:
    return RowComplete(
        result=result,
        wire_payload=build_row_complete_wire_payload(
            result,
            observation=observation,
            turn=turn,
            catalog=catalog,
            problem=problem,
            policy_steps_attempted=policy_steps_attempted,
            step_diagnostics=step_diagnostics,
            extra_diagnostics=extra_diagnostics,
        ),
    )


def _stopped_wire_payload_from_base(
    base: RowComplete,
    stopped_result: InferenceResult,
) -> RowCompleteWirePayload:
    return RowCompleteWirePayload(
        status=stopped_result.status,
        summary=format_inference_summary(stopped_result),
        solution_count=len(stopped_result.solutions),
        is_complete=True,
        solutions=base.wire_payload.solutions,
        diagnostics={
            **(base.wire_payload.diagnostics or {}),
            "stopped_reason": "cancelled",
        },
    )


def _row_complete_stopped_from_base(base: RowComplete) -> RowComplete:
    stopped_result = InferenceResult(
        status=STATUS_STOPPED,
        solutions=base.result.solutions,
        diagnostics={**base.result.diagnostics, "stopped_reason": "cancelled"},
    )
    return RowComplete(
        result=stopped_result,
        wire_payload=_stopped_wire_payload_from_base(base, stopped_result),
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
        if observation is None or turn is None:
            raise ValueError("observation and turn are required when ladder_state has solutions")
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
                observation=observation,
                turn=turn,
            )
        )
    stopped_result = InferenceResult(
        status=STATUS_STOPPED,
        solutions=(),
        diagnostics={"stopped_reason": "cancelled"},
    )
    return RowComplete(
        result=stopped_result,
        wire_payload=build_row_complete_wire_payload(
            stopped_result,
            summary_override="Build inference halted",
            force_is_complete=True,
        ),
    )
