"""Shared helpers for per-row and table-wide inference NDJSON streams."""

from __future__ import annotations

import queue
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    _inference_api_payload,
    format_inference_summary,
    inference_result_to_api_payload,
    serialize_solutions_with_arithmetic,
)
from api.analytics.military_score_inference.inference_path import (
    InferencePath,
    resolve_inference_path,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    GlobalPauseChanged,
    HeldSolutionsUpdated,
    InferenceStreamDomainEvent,
    RowComplete,
    RowFailed,
    TierProgress,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    create_inference_stream_orchestration,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.models.game import Score, TurnInfo
from api.transport.inference_stream import (
    inference_complete_event,
    inference_error_event,
    inference_global_pause_event,
    inference_progress_event,
    inference_solution_event,
)

_MULTiplexWaitSeconds = 0.05


def domain_event_to_wire_events(
    event: InferenceStreamDomainEvent,
    *,
    observation: InferenceObservation,
    turn: TurnInfo,
    on_finalize: Callable[[dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    """Convert one scheduler domain event into zero or more NDJSON wire dicts."""
    if isinstance(event, HeldSolutionsUpdated):
        serialized = serialize_solutions_with_arithmetic(
            event.observation or observation,
            event.catalog,
            event.solutions,
        )
        return [inference_solution_event(serialized)]

    if isinstance(event, TierProgress):
        return [
            inference_progress_event(
                policy_step_id=event.policy_step_id,
                combo_count=event.combo_count,
                held_count=event.held_count,
            )
        ]

    if isinstance(event, RowComplete):
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
            payload = _inference_api_payload(
                status=event.result.status,
                summary=summary,
                solutions=event.result.solutions,
                diagnostics=event.result.diagnostics,
            )
        if event.force_is_complete is not None:
            payload["isComplete"] = event.force_is_complete
        if on_finalize is not None:
            on_finalize(payload)
        return [
            inference_complete_event(
                status=str(payload.get("status", "")),
                summary=str(payload.get("summary", "")),
                solution_count=int(payload.get("solutionCount", 0)),
                is_complete=bool(payload.get("isComplete", True)),
                diagnostics=(
                    payload.get("diagnostics")
                    if isinstance(payload.get("diagnostics"), dict)
                    else None
                ),
            )
        ]

    if isinstance(event, RowFailed):
        return [inference_error_event(event.detail)]

    if isinstance(event, GlobalPauseChanged):
        return [inference_global_pause_event(paused=event.paused)]

    raise TypeError(f"Unsupported inference stream domain event: {type(event)!r}")


def row_domain_event_to_wire_events(
    row: ScheduledInferenceRow,
    event: InferenceStreamDomainEvent,
) -> list[dict[str, object]]:
    return domain_event_to_wire_events(
        event,
        observation=row.session.observation,
        turn=row.session.turn,
        on_finalize=row.session.on_finalize,
    )


def session_domain_event_to_wire_events(
    session: InferenceRowStreamSession,
    event: InferenceStreamDomainEvent,
) -> list[dict[str, object]]:
    return domain_event_to_wire_events(
        event,
        observation=session.observation,
        turn=session.turn,
        on_finalize=session.on_finalize,
    )


@dataclass(frozen=True)
class ScheduledInferenceRow:
    player_id: int
    session: InferenceRowStreamSession


def tag_inference_stream_event(
    event: dict[str, object],
    *,
    player_id: int,
) -> dict[str, object]:
    if event.get("type") == "globalPause":
        return event
    return {**event, "playerId": player_id}


def immediate_row_inference_events(
    turn: TurnInfo,
    player_id: int,
    *,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
) -> tuple[dict[str, object], ...] | None:
    """Return terminal wire events when no scheduler work is needed, else None."""
    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        return (
            inference_complete_event(
                status="player_not_found",
                summary=f"No score row for player {player_id}",
                solution_count=0,
                is_complete=True,
                diagnostics={"playerId": player_id, "turn": turn.settings.turn},
            ),
        )

    observation = build_inference_observation(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    path, _segments = resolve_inference_path(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if path != InferencePath.NO_PRIOR_TURN:
        return None

    from api.analytics.military_score_inference.analytic import _no_prior_turn_inference_result

    payload, _, _ = _no_prior_turn_inference_result(turn, observation)
    return (
        inference_complete_event(
            status=str(payload.get("status", STATUS_NO_PRIOR_TURN)),
            summary=str(payload.get("summary", "")),
            solution_count=int(payload.get("solutionCount", 0)),
            is_complete=bool(payload.get("isComplete", True)),
            diagnostics=(
                payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else None
            ),
        ),
    )


def schedule_inference_row(
    scheduler: InferenceRowScheduler,
    *,
    score: Score,
    turn: TurnInfo,
    player_id: int,
    game_id: int,
    perspective: int,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
) -> ScheduledInferenceRow:
    observation = build_inference_observation(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    path, _segments = resolve_inference_path(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    turn_number = turn.settings.turn
    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=observation,
        turn=turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=turn_number,
    )
    orchestration = create_inference_stream_orchestration(
        path,
        score,
        turn,
        segments=_segments,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    scheduler.enqueue_tier_ladder(session, orchestration=orchestration)
    return ScheduledInferenceRow(player_id=player_id, session=session)


def drain_available_multiplex_events(
    sessions: tuple[ScheduledInferenceRow, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str],
) -> Iterator[dict[str, object]]:
    """Yield any events already queued without blocking."""
    for row in sessions:
        if row.session.run_id in finished_run_ids:
            continue
        while True:
            try:
                domain_event = row.session.event_queue.get_nowait()
            except queue.Empty:
                break
            for event in row_domain_event_to_wire_events(row, domain_event):
                if tag_player_id:
                    event = tag_inference_stream_event(event, player_id=row.player_id)
                if event.get("type") in ("complete", "error"):
                    finished_run_ids.add(row.session.run_id)
                yield event


def iter_multiplexed_inference_events(
    sessions: tuple[ScheduledInferenceRow, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str] | None = None,
) -> Iterator[dict[str, object]]:
    """Round-robin blocking reads across row event queues until all rows finish."""
    finished = finished_run_ids if finished_run_ids is not None else set()
    pending_run_ids = {row.session.run_id for row in sessions if row.session.run_id not in finished}
    active_rows = list(sessions)
    cursor = 0
    while pending_run_ids and active_rows:
        row = active_rows[cursor % len(active_rows)]
        cursor += 1
        if row.session.run_id not in pending_run_ids:
            continue
        try:
            domain_event = row.session.event_queue.get(timeout=_MULTiplexWaitSeconds)
        except queue.Empty:
            continue
        for event in row_domain_event_to_wire_events(row, domain_event):
            if event.get("type") in ("complete", "error"):
                pending_run_ids.discard(row.session.run_id)
            if tag_player_id:
                yield tag_inference_stream_event(event, player_id=row.player_id)
            else:
                yield event


def cleanup_inference_stream_sessions(
    scheduler: InferenceRowScheduler,
    sessions: tuple[InferenceRowStreamSession, ...],
) -> None:
    for session in sessions:
        if not scheduler.preserve_session_on_stream_end(session):
            session.cancel_token.cancel()
            scheduler.unregister_session(session.run_id)
