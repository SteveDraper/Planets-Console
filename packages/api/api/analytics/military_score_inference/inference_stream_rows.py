"""Inference NDJSON stream helpers: row scheduling, multiplexing, and table-stream lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.fleet_torp_overlay import FleetTorpOverlay
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    STATUS_PLAYER_NOT_FOUND,
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
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    FleetTorpInputStatus,
    PriorTurnFleetTorpResolution,
)
from api.models.game import Score, TurnInfo
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.streaming.table_stream.connect import iter_table_stream_connect_with_scope
from api.streaming.table_stream.connect_policy import (
    DelegatingTableStreamConnectPolicy,
    TableStreamConnectPolicyHooks,
)
from api.streaming.table_stream.multiplex import (
    drain_available_multiplex_events as _drain_available_multiplex_events,
)
from api.streaming.table_stream.multiplex import (
    iter_multiplexed_stream_events,
)
from api.transport.inference_stream import (
    inference_complete_event,
    inference_global_pause_event,
)
from api.transport.inference_stream_wire import domain_event_to_wire_events

_TERMINAL_EVENT_TYPES = frozenset({"complete", "error"})


def row_domain_event_to_wire_events(
    row: ScheduledInferenceRow,
    event: InferenceStreamDomainEvent,
) -> list[dict[str, object]]:
    return domain_event_to_wire_events(
        event,
        observation=row.session.observation,
        turn=row.session.turn,
        fleet_torp_input_status=row.session.fleet_torp_input_status,
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
                status=STATUS_PLAYER_NOT_FOUND,
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
    fleet_torp_overlay: FleetTorpOverlay | None = None,
    fleet_torp_input_status: FleetTorpInputStatus | None = None,
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
        fleet_torp_overlay=fleet_torp_overlay,
        fleet_torp_input_status=fleet_torp_input_status,
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


def _inference_multiplex_event_to_wire_events(
    row: ScheduledInferenceRow,
    raw_event: InferenceStreamDomainEvent,
) -> Iterator[dict[str, object]]:
    yield from row_domain_event_to_wire_events(row, raw_event)


def drain_available_multiplex_events(
    sessions: tuple[ScheduledInferenceRow, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str],
) -> Iterator[dict[str, object]]:
    """Yield any events already queued without blocking."""
    return _drain_available_multiplex_events(
        sessions,
        tag_player_id=tag_player_id,
        finished_run_ids=finished_run_ids,
        event_to_wire_events=_inference_multiplex_event_to_wire_events,
        tag_event=lambda event, player_id: tag_inference_stream_event(
            event,
            player_id=player_id,
        ),
        terminal_types=_TERMINAL_EVENT_TYPES,
    )


def iter_multiplexed_inference_events(
    sessions: tuple[ScheduledInferenceRow, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str] | None = None,
    is_stream_active: Callable[[], bool] | None = None,
    session_provider: Callable[[], tuple[ScheduledInferenceRow, ...]] | None = None,
    pending_events_provider: Callable[[], list[dict[str, object]]] | None = None,
    wake_event: object | None = None,
) -> Iterator[dict[str, object]]:
    """Round-robin blocking reads across row event queues until rows finish."""
    return iter_multiplexed_stream_events(
        sessions,
        tag_player_id=tag_player_id,
        finished_run_ids=finished_run_ids,
        is_stream_active=is_stream_active,
        row_provider=session_provider,
        pending_events_provider=pending_events_provider,
        wake_event=wake_event,
        event_to_wire_events=_inference_multiplex_event_to_wire_events,
        tag_event=lambda event, player_id: tag_inference_stream_event(
            event,
            player_id=player_id,
        ),
        terminal_types=_TERMINAL_EVENT_TYPES,
    )


def cleanup_inference_stream_sessions(
    scheduler: InferenceRowScheduler,
    scope: InferenceStreamScope,
    sessions: tuple[InferenceRowStreamSession, ...],
    *,
    stream_token: str,
) -> None:
    """Tear down row runs when the table stream ends."""
    scheduler.end_inference_stream(scope, sessions, stream_token=stream_token)


def iter_scores_table_inference_events(
    turn: TurnInfo,
    player_ids: tuple[int, ...],
    *,
    game_id: int,
    perspective: int,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    reload_host_turn: Callable[[], TurnInfo] | None = None,
    resolve_mask_for_player: Callable[[int], ResolvedHullCatalogMask | None] | None = None,
    resolve_fleet_torp_resolution_for_player: Callable[[int], PriorTurnFleetTorpResolution]
    | None = None,
    persistence: InferenceRowPersistenceService | None = None,
    scheduler: InferenceRowScheduler | None = None,
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
    resolved_scheduler = scheduler or get_inference_row_scheduler()

    def policy_factory(
        stream_token: str,
    ) -> DelegatingTableStreamConnectPolicy[
        ScheduledInferenceRow,
        RowStreamAdmission,
        InferenceStreamDomainEvent,
    ]:
        controller = InferenceTableStreamController(
            scope=stream_scope,
            stream_token=stream_token,
            turn=turn,
            player_ids=player_ids,
            scheduler=resolved_scheduler,
            game_id=game_id,
            perspective=perspective,
            load_scoreboard_turn=load_scoreboard_turn,
            reload_host_turn=reload_host_turn,
            resolve_mask_for_player=resolve_mask_for_player,
            resolve_fleet_torp_resolution_for_player=resolve_fleet_torp_resolution_for_player,
            persistence=persistence,
        )
        return DelegatingTableStreamConnectPolicy(
            controller=controller,
            owns_table_stream_fn=lambda: resolved_scheduler.owns_table_stream(stream_token),
            hooks=TableStreamConnectPolicyHooks(
                preamble_events=lambda: (
                    inference_global_pause_event(
                        paused=bool(
                            resolved_scheduler.global_pause_status(stream_scope).get("paused")
                        ),
                    ),
                ),
                resolve_admission=controller.resolve_row_admission,
                dispatch_admission=controller.dispatch_row_admission,
                multiplex_event_to_wire_events=_inference_multiplex_event_to_wire_events,
                tag_event=lambda event, player_id: tag_inference_stream_event(
                    event,
                    player_id=player_id,
                ),
                terminal_types=lambda: _TERMINAL_EVENT_TYPES,
                end_sessions=lambda: cleanup_inference_stream_sessions(
                    resolved_scheduler,
                    stream_scope,
                    tuple(row.session for row in controller.current_scheduled_rows()),
                    stream_token=stream_token,
                ),
            ),
        )

    yield from iter_table_stream_connect_with_scope(
        begin_scope=lambda: resolved_scheduler.begin_scope(stream_scope),
        policy_factory=policy_factory,
        player_ids=player_ids,
    )
