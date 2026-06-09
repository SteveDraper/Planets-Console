"""Inference NDJSON stream helpers: row scheduling, multiplexing, and table-stream lifecycle."""

from __future__ import annotations

import queue
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    no_prior_turn_inference_api_payload,
)
from api.analytics.military_score_inference.inference_path import (
    InferencePath,
    resolve_inference_path,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    get_inference_row_scheduler,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    InferenceStreamDomainEvent,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    create_inference_stream_orchestration,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.models.game import Score, TurnInfo
from api.transport.inference_stream import inference_complete_event, inference_global_pause_event
from api.transport.inference_stream_wire import domain_event_to_wire_events

_MULTiplexWaitSeconds = 0.05


def row_domain_event_to_wire_events(
    row: ScheduledInferenceRow,
    event: InferenceStreamDomainEvent,
) -> list[dict[str, object]]:
    return domain_event_to_wire_events(
        event,
        observation=row.session.observation,
        turn=row.session.turn,
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
                solutions=[],
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

    payload = no_prior_turn_inference_api_payload(turn, observation)
    wire_solutions = payload.get("solutions")
    return (
        inference_complete_event(
            status=str(payload.get("status", STATUS_NO_PRIOR_TURN)),
            summary=str(payload.get("summary", "")),
            solution_count=int(payload.get("solutionCount", 0)),
            is_complete=bool(payload.get("isComplete", True)),
            diagnostics=(
                payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else None
            ),
            solutions=wire_solutions if isinstance(wire_solutions, list) else [],
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
    stream_token: str | None = None,
) -> ScheduledInferenceRow | None:
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
    orchestration = create_inference_stream_orchestration(
        path,
        score,
        turn,
        segments=_segments,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    scheduler.enqueue_tier_ladder(
        session,
        orchestration=orchestration,
        stream_token=stream_token,
    )
    if stream_token is not None and not scheduler.owns_table_stream(stream_token):
        return None
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
    is_stream_active: Callable[[], bool] | None = None,
) -> Iterator[dict[str, object]]:
    """Round-robin blocking reads across row event queues until all rows finish."""
    finished = finished_run_ids if finished_run_ids is not None else set()
    pending_run_ids = {row.session.run_id for row in sessions if row.session.run_id not in finished}
    active_rows = list(sessions)
    cursor = 0
    while pending_run_ids and active_rows:
        if is_stream_active is not None and not is_stream_active():
            return
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
    scope: InferenceStreamScope,
    sessions: tuple[InferenceRowStreamSession, ...],
    *,
    stream_token: str,
) -> None:
    """Tear down row runs when the table stream ends; always recalculate on reconnect."""
    if sessions:
        scheduler.end_inference_stream(scope, sessions, stream_token=stream_token)


def iter_scores_table_inference_events(
    turn: TurnInfo,
    player_ids: tuple[int, ...],
    *,
    game_id: int,
    perspective: int,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    resolve_mask_for_player: Callable[[int], ResolvedHullCatalogMask | None] | None = None,
) -> Iterator[dict[str, object]]:
    """Yield tagged inference events for all scoreboard rows on one NDJSON stream."""
    turn_number = turn.settings.turn
    stream_scope = InferenceStreamScope(
        game_id=game_id,
        perspective=perspective,
        turn_number=turn_number,
    )
    scheduler = get_inference_row_scheduler()
    stream_token = scheduler.begin_scope(stream_scope)
    pause_status = scheduler.global_pause_status(stream_scope)
    yield inference_global_pause_event(paused=bool(pause_status.get("paused")))

    scheduled_rows: list[ScheduledInferenceRow] = []
    finished_run_ids: set[str] = set()
    for player_id in player_ids:
        if not scheduler.owns_table_stream(stream_token):
            return

        immediate = immediate_row_inference_events(
            turn,
            player_id,
            load_scoreboard_turn=load_scoreboard_turn,
        )
        if immediate is not None:
            for event in immediate:
                yield tag_inference_stream_event(event, player_id=player_id)
            continue

        score = next(row for row in turn.scores if row.ownerid == player_id)
        resolved_mask = (
            resolve_mask_for_player(player_id) if resolve_mask_for_player is not None else None
        )
        scheduled_row = schedule_inference_row(
            scheduler,
            score=score,
            turn=turn,
            player_id=player_id,
            game_id=game_id,
            perspective=perspective,
            load_scoreboard_turn=load_scoreboard_turn,
            resolved_mask=resolved_mask,
            stream_token=stream_token,
        )
        if scheduled_row is None:
            return
        scheduled_rows.append(scheduled_row)
        yield from drain_available_multiplex_events(
            tuple(scheduled_rows),
            tag_player_id=True,
            finished_run_ids=finished_run_ids,
        )

    sessions = tuple(scheduled_rows)
    try:
        yield from iter_multiplexed_inference_events(
            sessions,
            tag_player_id=True,
            finished_run_ids=finished_run_ids,
            is_stream_active=lambda: scheduler.owns_table_stream(stream_token),
        )
    finally:
        cleanup_inference_stream_sessions(
            scheduler,
            stream_scope,
            tuple(row.session for row in sessions),
            stream_token=stream_token,
        )
