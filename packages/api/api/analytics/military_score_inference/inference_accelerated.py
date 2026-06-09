"""Accelerated-start segment execution and stream terminal row builders.

Batch JSON (``run_accelerated_split_inference``) runs a full policy ladder per segment
with a per-case time budget. SPA streaming runs one tier job at a time via the inference
row scheduler and ``InferenceStreamOrchestration``; segments chain without a row time cap.
Both paths share segment payload builders and terminal status aggregation here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.military_score_inference.accelerated_start import AcceleratedInferenceSegment
from api.analytics.military_score_inference.actions import (
    DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    ActionCatalog,
)
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    _serialize_solution_with_arithmetic,
    inference_api_payload,
    inference_result_to_api_payload,
)
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_target import (
    observation_from_accelerated_segment,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_INVALID_PROBLEM,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
)
from api.models.game import TurnInfo
from api.models.player import Score

AcceleratedSegmentArtifacts = tuple[InferenceObservation, ActionCatalog | None]


@dataclass(frozen=True)
class AcceleratedSegmentResult:
    """Policy-ladder outcome for one accelerated inference segment."""

    segment: AcceleratedInferenceSegment
    observation: InferenceObservation
    result: InferenceResult
    catalog: ActionCatalog | None
    problem: InferenceProblem | None
    policy_steps_attempted: list[str]
    step_diagnostics: list[dict[str, object]]
    payload: dict[str, object] | None = None


def run_accelerated_segment_policy_ladder(
    score: Score,
    turn: TurnInfo,
    segment: AcceleratedInferenceSegment,
    *,
    max_solutions: int,
    time_limit_seconds: float | None,
    cancel_token: InferenceCancelToken | None = None,
    on_admitted: Callable[[InferenceSolution], None] | None = None,
) -> AcceleratedSegmentResult:
    """Run the policy ladder for one accelerated segment."""
    observation = observation_from_accelerated_segment(score, turn, segment)
    resolved_time_limit = (
        time_limit_seconds
        if time_limit_seconds is not None
        else DEFAULT_INFERENCE_TIME_LIMIT_SECONDS
    )
    result, catalog, problem, policy_steps_attempted, step_diagnostics = solve_with_policy_ladder(
        observation,
        turn,
        max_solutions=max_solutions,
        time_limit_seconds=resolved_time_limit,
        cancel_token=cancel_token,
        on_admitted=on_admitted,
    )
    return AcceleratedSegmentResult(
        segment=segment,
        observation=observation,
        result=result,
        catalog=catalog,
        problem=problem,
        policy_steps_attempted=policy_steps_attempted,
        step_diagnostics=step_diagnostics,
    )


def build_accelerated_segment_payload(
    segment: AcceleratedInferenceSegment,
    segment_observation: InferenceObservation,
    result: InferenceResult,
    catalog: ActionCatalog | None,
    *,
    policy_steps_attempted: list[str],
    step_diagnostics: list[dict[str, object]],
) -> dict[str, object]:
    """Shape one accelerated segment solve into the diagnostics segment payload."""
    return {
        "segmentId": segment.segment_id,
        "hostTurn": segment.host_turn,
        "status": result.status,
        "solutionCount": len(result.solutions),
        "militaryDelta2x": segment.military_delta_2x,
        "warshipDelta": segment.warship_delta,
        "freighterDelta": segment.freighter_delta,
        "policyStepsAttempted": policy_steps_attempted,
        "policyStepAttempts": step_diagnostics,
        "solutions": (
            [
                _serialize_solution_with_arithmetic(
                    segment_observation,
                    catalog,
                    solution,
                )
                for solution in result.solutions
            ]
            if catalog is not None
            else []
        ),
    }


def accelerated_split_status(
    segment_payloads: list[dict[str, object]],
    combined_time_limited: bool,
) -> str:
    statuses = [
        payload["status"] for payload in segment_payloads if isinstance(payload["status"], str)
    ]
    if any(status == STATUS_NO_EXACT_SOLUTION for status in statuses):
        return STATUS_NO_EXACT_SOLUTION
    if any(status == STATUS_INVALID_PROBLEM for status in statuses):
        return STATUS_INVALID_PROBLEM
    if combined_time_limited or any(status == STATUS_TIME_LIMITED for status in statuses):
        return STATUS_TIME_LIMITED
    return STATUS_EXACT


def accelerated_split_missing_reported_segment_result(
    score: Score,
    turn: TurnInfo,
    *,
    segment_payloads: list[dict[str, object]],
    segment_artifacts: dict[int, AcceleratedSegmentArtifacts],
) -> tuple[
    dict[str, object],
    InferenceObservation,
    ActionCatalog | None,
    dict[int, AcceleratedSegmentArtifacts],
]:
    from api.analytics.military_score_inference.analytic import (
        build_inference_observation,
        build_inference_solver_diagnostics,
    )

    reason = "accelerated_split_missing_reported_segment"
    fallback_observation = build_inference_observation(score, turn)
    return (
        inference_api_payload(
            status=STATUS_INVALID_PROBLEM,
            summary=f"Invalid inference problem: {reason}",
            solutions=(),
            diagnostics=build_inference_solver_diagnostics(
                turn=turn.settings.turn,
                observation=fallback_observation,
                turn_info=turn,
                extra={
                    "reason": reason,
                    "accelerated_segments": segment_payloads,
                },
            ),
        ),
        fallback_observation,
        None,
        segment_artifacts,
    )


def run_accelerated_split_inference(
    score: Score,
    turn: TurnInfo,
    segments: tuple[AcceleratedInferenceSegment, ...],
    *,
    time_limit_seconds: float = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> tuple[
    dict[str, object],
    InferenceObservation,
    ActionCatalog | None,
    dict[int, AcceleratedSegmentArtifacts],
]:
    """Solve accel-window and reported-host-turn targets independently."""
    segment_count = len(segments)
    per_segment_time = time_limit_seconds / segment_count

    segment_payloads: list[dict[str, object]] = []
    segment_artifacts: dict[int, AcceleratedSegmentArtifacts] = {}
    reported_observation: InferenceObservation | None = None
    reported_catalog: ActionCatalog | None = None
    reported_problem: InferenceProblem | None = None
    reported_result: InferenceResult | None = None
    reported_policy_steps: list[str] = []
    reported_step_diagnostics: list[dict[str, object]] = []
    combined_time_limited = False

    for segment in segments:
        ladder_result = run_accelerated_segment_policy_ladder(
            score,
            turn,
            segment,
            max_solutions=20,
            time_limit_seconds=per_segment_time,
        )
        if segment.segment_id == "reported_host_turn":
            reported_observation = ladder_result.observation
            reported_catalog = ladder_result.catalog
            reported_problem = ladder_result.problem
            reported_result = ladder_result.result
            reported_policy_steps = ladder_result.policy_steps_attempted
            reported_step_diagnostics = ladder_result.step_diagnostics
        if ladder_result.result.status == STATUS_TIME_LIMITED:
            combined_time_limited = True

        segment_artifacts[segment.host_turn] = (
            ladder_result.observation,
            ladder_result.catalog,
        )
        segment_payloads.append(
            build_accelerated_segment_payload(
                segment,
                ladder_result.observation,
                ladder_result.result,
                ladder_result.catalog,
                policy_steps_attempted=ladder_result.policy_steps_attempted,
                step_diagnostics=ladder_result.step_diagnostics,
            )
        )

    if (
        reported_observation is None
        or reported_catalog is None
        or reported_problem is None
        or reported_result is None
    ):
        return accelerated_split_missing_reported_segment_result(
            score,
            turn,
            segment_payloads=segment_payloads,
            segment_artifacts=segment_artifacts,
        )

    overall_status = accelerated_split_status(segment_payloads, combined_time_limited)
    primary_result = InferenceResult(
        status=overall_status,
        solutions=reported_result.solutions,
        diagnostics={
            **reported_result.diagnostics,
            "accelerated_segments": segment_payloads,
        },
    )

    return (
        inference_result_to_api_payload(
            primary_result,
            reported_catalog,
            reported_observation,
            turn,
            reported_problem,
            policy_steps_attempted=reported_policy_steps,
            step_diagnostics=reported_step_diagnostics,
            extra_diagnostics={"accelerated_segments": segment_payloads},
        ),
        reported_observation,
        reported_catalog,
        segment_artifacts,
    )


def build_accelerated_split_stream_row_complete(
    score: Score,
    turn: TurnInfo,
    *,
    segment_solves: tuple[AcceleratedSegmentResult, ...],
    combined_time_limited: bool,
) -> RowComplete:
    """Build terminal stream state for an accelerated split row."""
    segment_payloads = [
        segment.payload for segment in segment_solves if segment.payload is not None
    ]
    reported = next(
        (
            segment
            for segment in segment_solves
            if segment.segment.segment_id == "reported_host_turn"
        ),
        None,
    )
    if reported is None or reported.catalog is None or reported.problem is None:
        missing = accelerated_split_missing_reported_segment_result(
            score,
            turn,
            segment_payloads=segment_payloads,
            segment_artifacts={
                segment.segment.host_turn: (segment.observation, segment.catalog)
                for segment in segment_solves
            },
        )
        missing_payload, missing_observation, _, _ = missing
        return RowComplete(
            result=InferenceResult(
                status=str(missing_payload.get("status", STATUS_INVALID_PROBLEM)),
                solutions=(),
                diagnostics=(
                    missing_payload.get("diagnostics")
                    if isinstance(missing_payload.get("diagnostics"), dict)
                    else {"reason": "accelerated_split_missing_reported_segment"}
                ),
            ),
            summary_override=str(missing_payload.get("summary", "Invalid inference problem")),
            wire_observation=missing_observation,
            wire_turn=turn,
        )

    overall_status = accelerated_split_status(segment_payloads, combined_time_limited)
    return RowComplete(
        result=InferenceResult(
            status=overall_status,
            solutions=reported.result.solutions,
            diagnostics={
                **reported.result.diagnostics,
                "accelerated_segments": segment_payloads,
            },
        ),
        catalog=reported.catalog,
        problem=reported.problem,
        policy_steps_attempted=reported.policy_steps_attempted,
        step_diagnostics=reported.step_diagnostics,
        wire_observation=reported.observation,
        wire_turn=turn,
        extra_diagnostics={"accelerated_segments": segment_payloads},
    )


def build_accelerated_backfill_stream_row_complete(
    row_score: Score,
    row_turn: TurnInfo,
    *,
    target_host_turn: int,
    source_turn_number: int,
    source_turn: TurnInfo,
    segment_solves: tuple[AcceleratedSegmentResult, ...],
) -> RowComplete:
    """Build terminal stream state for an accelerated backfill row."""
    segment_payloads = [
        segment.payload for segment in segment_solves if segment.payload is not None
    ]
    target = next(
        (segment for segment in segment_solves if segment.segment.host_turn == target_host_turn),
        None,
    )
    if target is None or target.catalog is None or target.problem is None:
        from api.analytics.military_score_inference.analytic import build_inference_observation

        return RowComplete(
            result=InferenceResult(
                status=STATUS_NO_PRIOR_TURN,
                solutions=(),
                diagnostics={"reason": "accelerated_backfill_unavailable"},
            ),
            summary_override="Prior turn score data unavailable",
            wire_observation=build_inference_observation(row_score, row_turn),
            wire_turn=row_turn,
        )

    return RowComplete(
        result=InferenceResult(
            status=target.result.status,
            solutions=target.result.solutions,
            diagnostics={
                **target.result.diagnostics,
                "accelerated_segments": segment_payloads,
            },
        ),
        catalog=target.catalog,
        problem=target.problem,
        policy_steps_attempted=target.policy_steps_attempted,
        step_diagnostics=target.step_diagnostics,
        wire_observation=target.observation,
        wire_turn=source_turn,
        extra_diagnostics={
            "accelerated_backfill": True,
            "accelerated_backfill_source_turn": source_turn_number,
            "accelerated_backfill_host_turn": target_host_turn,
            "accelerated_backfill_segment_id": target.segment.segment_id,
            "accelerated_segments": segment_payloads,
        },
    )
