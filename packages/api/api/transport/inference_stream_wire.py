"""Map inference stream domain events to NDJSON wire dicts."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_api_payload import (
    format_inference_summary,
    inference_api_payload,
    inference_result_to_api_payload,
    serialize_solutions_with_arithmetic,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    GlobalPauseChanged,
    HeldSolutionsUpdated,
    InferenceStreamDomainEvent,
    RowComplete,
    RowFailed,
    TierProgress,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.models.game import TurnInfo
from api.transport.inference_stream import (
    inference_complete_event,
    inference_error_event,
    inference_global_pause_event,
    inference_progress_event,
    inference_solution_event,
)


def row_complete_to_complete_wire_event(
    event: RowComplete,
    *,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> dict[str, object]:
    wire_observation = event.wire_observation or observation
    wire_turn = event.wire_turn or turn
    if event.catalog is not None and event.problem is not None:
        payload = inference_result_to_api_payload(
            event.result,
            event.catalog,
            wire_observation,
            wire_turn,
            event.problem,
            policy_steps_attempted=event.policy_steps_attempted,
            step_diagnostics=event.step_diagnostics,
            extra_diagnostics=event.extra_diagnostics,
        )
    else:
        summary = event.summary_override or format_inference_summary(event.result)
        payload = inference_api_payload(
            status=event.result.status,
            summary=summary,
            solutions=event.result.solutions,
            diagnostics=event.result.diagnostics,
        )
    if event.force_is_complete is not None:
        payload["isComplete"] = event.force_is_complete
    diagnostics = payload.get("diagnostics")
    return inference_complete_event(
        status=str(payload.get("status", "")),
        summary=str(payload.get("summary", "")),
        solution_count=int(payload.get("solutionCount", 0)),
        is_complete=bool(payload.get("isComplete", True)),
        diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
    )


def domain_event_to_wire_events(
    event: InferenceStreamDomainEvent,
    *,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> list[dict[str, object]]:
    """Convert one scheduler domain event into zero or more NDJSON wire dicts."""
    if isinstance(event, HeldSolutionsUpdated):
        wire_observation = event.observation or observation
        serialized = serialize_solutions_with_arithmetic(
            wire_observation,
            event.catalog,
            event.solutions,
        )
        segment_id = event.segment_id
        return [
            inference_solution_event(
                serialized,
                segment_id=segment_id,
                scoreboard_delta_source=(
                    wire_observation.scoreboard_delta_source if segment_id is not None else None
                ),
            )
        ]

    if isinstance(event, TierProgress):
        return [
            inference_progress_event(
                policy_step_id=event.policy_step_id,
                combo_count=event.combo_count,
                held_count=event.held_count,
            )
        ]

    if isinstance(event, RowComplete):
        return [row_complete_to_complete_wire_event(event, observation=observation, turn=turn)]

    if isinstance(event, RowFailed):
        return [inference_error_event(event.detail)]

    if isinstance(event, GlobalPauseChanged):
        return [inference_global_pause_event(paused=event.paused)]

    raise TypeError(f"Unsupported inference stream domain event: {type(event)!r}")
