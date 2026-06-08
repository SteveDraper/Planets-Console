"""Shared helpers for per-row and table-wide inference NDJSON streams."""

from __future__ import annotations

import queue
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    _inference_api_payload,
)
from api.analytics.military_score_inference.inference_path import (
    InferencePath,
    resolve_inference_path,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.solver import STATUS_STOPPED
from api.models.game import Score, TurnInfo
from api.transport.inference_stream import inference_complete_event

_MULTiplexWaitSeconds = 0.05


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
    resolved_mask: ResolvedHullCatalogMask | None = None,
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
        resolved_mask=resolved_mask,
    )
    if path == InferencePath.POLICY_LADDER:
        scheduler.enqueue_tier_ladder(session)
    else:

        def run_full_row(row_session: InferenceRowStreamSession) -> dict[str, object]:
            if row_session.cancel_token.is_cancelled():
                return _inference_api_payload(
                    status=STATUS_STOPPED,
                    summary="Build inference halted",
                    solutions=(),
                    diagnostics={"stopped_reason": "cancelled"},
                )
            payload, _, _ = run_inference_with_artifacts(
                score,
                turn,
                load_scoreboard_turn=load_scoreboard_turn,
                resolved_mask=row_session.resolved_mask,
            )
            if row_session.cancel_token.is_cancelled():
                payload = {
                    **payload,
                    "status": STATUS_STOPPED,
                    "summary": "Build inference halted",
                    "isComplete": True,
                }
            return payload

        scheduler.enqueue_full_row(session, run_full_row)
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
                event = row.session.event_queue.get_nowait()
            except queue.Empty:
                break
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
            event = row.session.event_queue.get(timeout=_MULTiplexWaitSeconds)
        except queue.Empty:
            continue
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
