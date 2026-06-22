"""Map inference stream domain events to NDJSON wire dicts."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_api_payload import (
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


def inference_api_payload_to_wire_complete(
    payload: dict[str, object],
) -> dict[str, object]:
    """Shape a scores row inference API payload into a terminal wire ``complete`` event."""
    wire_solutions = payload.get("solutions")
    diagnostics = payload.get("diagnostics")
    return inference_complete_event(
        status=str(payload.get("status", "")),
        summary=str(payload.get("summary", "")),
        solution_count=int(payload.get("solutionCount", 0)),
        is_complete=bool(payload.get("isComplete", True)),
        diagnostics=diagnostics if isinstance(diagnostics, dict) else None,
        solutions=wire_solutions if isinstance(wire_solutions, list) else [],
    )


def row_complete_to_complete_wire_event(
    event: RowComplete,
    *,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> dict[str, object]:
    payload = event.wire_payload
    return inference_complete_event(
        status=payload.status,
        summary=payload.summary,
        solution_count=payload.solution_count,
        is_complete=payload.is_complete,
        diagnostics=payload.diagnostics,
        solutions=payload.solutions,
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
