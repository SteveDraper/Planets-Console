"""Inference NDJSON stream helpers: row scheduling, multiplexing, and table-stream lifecycle."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

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
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
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


@dataclass(frozen=True)
class ImmediateRowAdmission:
    kind: Literal["immediate"] = "immediate"
    events: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class CachedCompleteRowAdmission:
    kind: Literal["cached"] = "cached"
    event: dict[str, object] | None = None


@dataclass(frozen=True)
class ScheduleRowAdmission:
    kind: Literal["schedule"] = "schedule"


RowStreamAdmission = ImmediateRowAdmission | CachedCompleteRowAdmission | ScheduleRowAdmission


def resolve_row_stream_admission(
    turn: TurnInfo,
    player_id: int,
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    persistence: InferenceRowPersistenceService | None = None,
    force_schedule: bool = False,
) -> RowStreamAdmission:
    """Decide whether a table-stream row is immediate, cached-complete, or tier-scheduled."""
    if not force_schedule:
        immediate = immediate_row_inference_events(
            turn,
            player_id,
            load_scoreboard_turn=load_scoreboard_turn,
        )
        if immediate is not None:
            return ImmediateRowAdmission(events=immediate)

        if persistence is not None:
            cached = persistence.wire_complete_for_row(
                game_id,
                perspective,
                turn_number,
                player_id,
            )
            if cached is not None:
                return CachedCompleteRowAdmission(event=cached)

    return ScheduleRowAdmission()


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
    session_provider: Callable[[], tuple[ScheduledInferenceRow, ...]] | None = None,
    wake_event: threading.Event | None = None,
) -> Iterator[dict[str, object]]:
    """Round-robin blocking reads across row event queues until rows finish.

    When ``is_stream_active`` is provided, keep waiting (including on ``wake_event``)
    while the table stream remains active so in-place row reschedule can enqueue work
    after every row has already reached a terminal event.
    """
    finished = finished_run_ids if finished_run_ids is not None else set()

    def active_sessions() -> tuple[ScheduledInferenceRow, ...]:
        if session_provider is not None:
            return session_provider()
        return sessions

    def refresh_pending_run_ids() -> set[str]:
        return {
            row.session.run_id for row in active_sessions() if row.session.run_id not in finished
        }

    pending_run_ids = refresh_pending_run_ids()
    cursor = 0

    def should_continue() -> bool:
        if is_stream_active is not None:
            return is_stream_active()
        return bool(pending_run_ids)

    while should_continue():
        if is_stream_active is not None and not is_stream_active():
            return
        if not pending_run_ids:
            if wake_event is not None:
                wake_event.wait(timeout=_MULTiplexWaitSeconds)
                if wake_event.is_set():
                    wake_event.clear()
                pending_run_ids = refresh_pending_run_ids()
            continue
        active_rows = list(active_sessions())
        if not active_rows:
            continue
        row = active_rows[cursor % len(active_rows)]
        cursor += 1
        if row.session.run_id not in pending_run_ids:
            continue
        try:
            domain_event = row.session.event_queue.get(timeout=_MULTiplexWaitSeconds)
        except queue.Empty:
            if wake_event is not None and wake_event.is_set():
                wake_event.clear()
                pending_run_ids = refresh_pending_run_ids()
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
    """Tear down row runs when the table stream ends.

    A later reconnect replays persisted complete rows from cache and schedules
    any rows that were still in progress or invalidated.
    """
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
    persistence: InferenceRowPersistenceService | None = None,
) -> Iterator[dict[str, object]]:
    """Yield tagged inference events for all scoreboard rows on one NDJSON stream."""
    from api.analytics.military_score_inference.inference_table_stream_controller import (
        InferenceTableStreamController,
    )

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

    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=turn,
        player_ids=player_ids,
        scheduler=scheduler,
        game_id=game_id,
        perspective=perspective,
        load_scoreboard_turn=load_scoreboard_turn,
        resolve_mask_for_player=resolve_mask_for_player,
        persistence=persistence,
    )
    controller.attach()

    try:
        for player_id in player_ids:
            if not scheduler.owns_table_stream(stream_token):
                return

            admission = controller.resolve_row_admission(player_id)
            if isinstance(admission, ImmediateRowAdmission):
                for event in admission.events:
                    yield tag_inference_stream_event(event, player_id=player_id)
                continue
            if isinstance(admission, CachedCompleteRowAdmission):
                assert admission.event is not None
                yield tag_inference_stream_event(admission.event, player_id=player_id)
                continue

            scheduled_row = controller.schedule_player_row(player_id)
            if scheduled_row is None:
                return
            controller.register_scheduled_row(player_id, scheduled_row)
            yield from drain_available_multiplex_events(
                controller.current_scheduled_rows(),
                tag_player_id=True,
                finished_run_ids=controller.finished_run_ids,
            )

        if player_ids:
            try:
                yield from iter_multiplexed_inference_events(
                    controller.current_scheduled_rows(),
                    tag_player_id=True,
                    finished_run_ids=controller.finished_run_ids,
                    is_stream_active=lambda: scheduler.owns_table_stream(stream_token),
                    session_provider=controller.current_scheduled_rows,
                    wake_event=controller.wake_multiplex,
                )
            finally:
                cleanup_inference_stream_sessions(
                    scheduler,
                    stream_scope,
                    tuple(row.session for row in controller.current_scheduled_rows()),
                    stream_token=stream_token,
                )
    finally:
        controller.detach()
