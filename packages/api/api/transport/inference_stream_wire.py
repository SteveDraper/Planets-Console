"""Map inference stream domain events to NDJSON wire dicts."""

from __future__ import annotations

from api.analytics.military_score_inference.host_turn_targets import (
    host_turn_functional_target_to_wire_dict,
    host_turn_functional_targets_from_wire_list,
)
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
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    fleet_torp_complete_wire_fields_from_diagnostics,
)
from api.models.game import TurnInfo
from api.transport.inference_stream import (
    inference_complete_event,
    inference_error_event,
    inference_global_pause_event,
    inference_progress_event,
    inference_solution_event,
)


def _complete_event_fleet_torp_wire_fields(
    *,
    diagnostics: dict[str, object] | None,
    fleet_torp_input_status: object | None = None,
    fleet_torp_overlay_belief_set_torp_ids: object | None = None,
) -> tuple[str | None, list[int] | None]:
    if fleet_torp_input_status is not None or fleet_torp_overlay_belief_set_torp_ids is not None:
        status = str(fleet_torp_input_status) if fleet_torp_input_status is not None else None
        belief_ids: list[int] | None = None
        if isinstance(fleet_torp_overlay_belief_set_torp_ids, list):
            belief_ids = [
                torp_id
                for torp_id in fleet_torp_overlay_belief_set_torp_ids
                if isinstance(torp_id, int)
            ]
        return status, belief_ids

    return fleet_torp_complete_wire_fields_from_diagnostics(diagnostics)


def _wire_host_turn_targets(
    host_turn_targets: object,
) -> list[dict[str, object]] | None:
    parsed = host_turn_functional_targets_from_wire_list(host_turn_targets)
    if parsed is None:
        return None
    return [host_turn_functional_target_to_wire_dict(target) for target in parsed]


def inference_api_payload_to_wire_complete(
    payload: dict[str, object],
) -> dict[str, object]:
    """Shape a scores row inference API payload into a terminal wire ``complete`` event."""
    wire_solutions = payload.get("solutions")
    diagnostics = payload.get("diagnostics")
    diagnostics_dict = diagnostics if isinstance(diagnostics, dict) else None
    fleet_torp_input_status, fleet_torp_overlay_belief_set_torp_ids = (
        _complete_event_fleet_torp_wire_fields(
            diagnostics=diagnostics_dict,
            fleet_torp_input_status=payload.get("fleetTorpInputStatus"),
            fleet_torp_overlay_belief_set_torp_ids=payload.get("fleetTorpOverlayBeliefSetTorpIds"),
        )
    )
    return inference_complete_event(
        status=str(payload.get("status", "")),
        summary=str(payload.get("summary", "")),
        solution_count=int(payload.get("solutionCount", 0)),
        is_complete=bool(payload.get("isComplete", True)),
        diagnostics=diagnostics_dict,
        solutions=wire_solutions if isinstance(wire_solutions, list) else [],
        host_turn_targets=_wire_host_turn_targets(payload.get("hostTurnTargets")),
        fleet_torp_input_status=fleet_torp_input_status,
        fleet_torp_overlay_belief_set_torp_ids=fleet_torp_overlay_belief_set_torp_ids,
    )


def row_complete_to_complete_wire_event(
    event: RowComplete,
    *,
    observation: InferenceObservation,
    turn: TurnInfo,
) -> dict[str, object]:
    payload = event.wire_payload
    wire_targets = None
    if payload.host_turn_targets is not None:
        wire_targets = [
            host_turn_functional_target_to_wire_dict(target) for target in payload.host_turn_targets
        ]
    fleet_torp_input_status, fleet_torp_overlay_belief_set_torp_ids = (
        fleet_torp_complete_wire_fields_from_diagnostics(payload.diagnostics)
    )
    return inference_complete_event(
        status=payload.status,
        summary=payload.summary,
        solution_count=payload.solution_count,
        is_complete=payload.is_complete,
        diagnostics=payload.diagnostics,
        solutions=payload.solutions,
        host_turn_targets=wire_targets,
        fleet_torp_input_status=fleet_torp_input_status,
        fleet_torp_overlay_belief_set_torp_ids=fleet_torp_overlay_belief_set_torp_ids,
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
