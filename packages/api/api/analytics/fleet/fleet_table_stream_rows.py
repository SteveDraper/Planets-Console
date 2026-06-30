"""Fleet table NDJSON stream helpers: player scheduling, multiplexing, and lifecycle."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.fleet_table_player_run import (
    FleetPlayerStreamSession,
    ScheduledFleetPlayer,
    run_fleet_player_materialization_job,
    wire_cached_player_events,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FleetTableStreamScheduler,
    TableStreamScopeAlreadyActive,
    get_fleet_table_stream_scheduler,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo
from api.transport.fleet_table_stream import (
    TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
    fleet_error_event,
)

_MULTiplexWaitSeconds = 0.05


@dataclass(frozen=True)
class ImmediatePlayerAdmission:
    kind: Literal["immediate"] = "immediate"
    events: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class CachedCompletePlayerAdmission:
    kind: Literal["cached"] = "cached"
    events: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class SchedulePlayerAdmission:
    kind: Literal["schedule"] = "schedule"


PlayerStreamAdmission = (
    ImmediatePlayerAdmission | CachedCompletePlayerAdmission | SchedulePlayerAdmission
)


@dataclass(frozen=True)
class PlayerAdmissionDispatch:
    wire_events: tuple[dict[str, object], ...] = ()
    scheduled_player: ScheduledFleetPlayer | None = None
    schedule_failed: bool = False


def tag_fleet_table_stream_event(
    event: dict[str, object],
    *,
    player_id: int,
) -> dict[str, object]:
    if "playerId" in event:
        return event
    return {**event, "playerId": player_id}


def resolve_player_stream_admission(
    persistence: FleetSnapshotPersistenceService,
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
    player_id: int,
    force_schedule: bool = False,
) -> PlayerStreamAdmission:
    """Decide whether a fleet table player is cached-complete or needs scheduling."""
    if not force_schedule:
        persisted = persistence.get_ledger(game_id, perspective, turn_number, player_id)
        if persisted is not None and persisted.provenance.is_final:
            return CachedCompletePlayerAdmission(events=wire_cached_player_events(persisted))
    return SchedulePlayerAdmission()


def schedule_fleet_player_run(
    scheduler: FleetTableStreamScheduler,
    *,
    turn: TurnInfo,
    player_id: int,
    game_id: int,
    perspective: int,
    fleet_services: FleetComputeServices,
    persistence: FleetSnapshotPersistenceService,
    stream_token: str | None = None,
) -> ScheduledFleetPlayer | None:
    session = FleetPlayerStreamSession(
        player_id=player_id,
        turn=turn,
        game_id=game_id,
        perspective=perspective,
    )

    def materialize(active_session: FleetPlayerStreamSession) -> None:
        run_fleet_player_materialization_job(
            active_session,
            fleet_services=fleet_services,
            persistence=persistence,
        )

    scheduler.enqueue_player_run(
        session,
        materialize,
        stream_token=stream_token,
    )
    if stream_token is not None and not scheduler.owns_table_stream(stream_token):
        return None
    active_session = scheduler.row_run_for_player(
        FleetTableStreamScope(
            game_id=game_id,
            perspective=perspective,
            turn_number=turn.settings.turn,
        ),
        player_id,
    )
    if active_session is None:
        return None
    return ScheduledFleetPlayer(player_id=player_id, session=active_session)


def drain_available_multiplex_events(
    players: tuple[ScheduledFleetPlayer, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str],
) -> Iterator[dict[str, object]]:
    """Yield any events already queued without blocking."""
    for row in players:
        if row.session.run_id in finished_run_ids:
            continue
        while True:
            try:
                event = row.session.event_queue.get_nowait()
            except queue.Empty:
                break
            if tag_player_id:
                event = tag_fleet_table_stream_event(event, player_id=row.player_id)
            if event.get("type") in ("complete", "error"):
                finished_run_ids.add(row.session.run_id)
            yield event


def iter_multiplexed_fleet_table_events(
    players: tuple[ScheduledFleetPlayer, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str] | None = None,
    is_stream_active: Callable[[], bool] | None = None,
    player_provider: Callable[[], tuple[ScheduledFleetPlayer, ...]] | None = None,
    pending_events_provider: Callable[[], list[dict[str, object]]] | None = None,
    wake_event: threading.Event | None = None,
) -> Iterator[dict[str, object]]:
    """Round-robin blocking reads across player event queues until players finish."""
    finished = finished_run_ids if finished_run_ids is not None else set()
    cursor = 0

    def active_players() -> tuple[ScheduledFleetPlayer, ...]:
        if player_provider is not None:
            return player_provider()
        return players

    def refresh_pending_run_ids() -> set[str]:
        return {
            row.session.run_id for row in active_players() if row.session.run_id not in finished
        }

    pending_run_ids = refresh_pending_run_ids()

    def should_continue() -> bool:
        if is_stream_active is not None:
            return is_stream_active()
        return bool(pending_run_ids)

    while should_continue():
        if is_stream_active is not None and not is_stream_active():
            return
        if pending_events_provider is not None:
            for event in pending_events_provider():
                yield event
        if not pending_run_ids:
            if wake_event is not None:
                wake_event.wait(timeout=_MULTiplexWaitSeconds)
                if wake_event.is_set():
                    wake_event.clear()
                pending_run_ids = refresh_pending_run_ids()
            continue
        active_rows = list(active_players())
        if not active_rows:
            continue
        row = active_rows[cursor % len(active_rows)]
        cursor += 1
        if row.session.run_id not in pending_run_ids:
            continue
        try:
            event = row.session.event_queue.get(timeout=_MULTiplexWaitSeconds)
        except queue.Empty:
            if wake_event is not None and wake_event.is_set():
                wake_event.clear()
                pending_run_ids = refresh_pending_run_ids()
            continue
        if tag_player_id:
            event = tag_fleet_table_stream_event(event, player_id=row.player_id)
        if event.get("type") in ("complete", "error"):
            pending_run_ids.discard(row.session.run_id)
            finished.add(row.session.run_id)
        yield event


def cleanup_fleet_table_stream_sessions(
    scheduler: FleetTableStreamScheduler,
    scope: FleetTableStreamScope,
    sessions: tuple[FleetPlayerStreamSession, ...],
    *,
    stream_token: str,
) -> None:
    if sessions:
        scheduler.end_fleet_table_stream(scope, sessions, stream_token=stream_token)


def iter_fleet_table_stream_events(
    turn: TurnInfo,
    player_ids: tuple[int, ...],
    *,
    game_id: int,
    perspective: int,
    fleet_services: FleetComputeServices,
    persistence: FleetSnapshotPersistenceService,
    scheduler: FleetTableStreamScheduler | None = None,
) -> Iterator[dict[str, object]]:
    """Yield tagged fleet table events for all requested players on one NDJSON stream."""
    from api.analytics.fleet.fleet_table_stream_controller import FleetTableStreamController

    turn_number = turn.settings.turn
    stream_scope = FleetTableStreamScope(
        game_id=game_id,
        perspective=perspective,
        turn_number=turn_number,
    )
    scheduler = scheduler or get_fleet_table_stream_scheduler()
    try:
        stream_token = scheduler.begin_scope(stream_scope)
    except TableStreamScopeAlreadyActive:
        yield fleet_error_event(TABLE_STREAM_ALREADY_ACTIVE_DETAIL)
        return

    controller = FleetTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=turn,
        player_ids=player_ids,
        scheduler=scheduler,
        fleet_services=fleet_services,
        persistence=persistence,
    )
    controller.attach()

    def dispatch_player_admission(
        player_id: int,
        admission: PlayerStreamAdmission,
    ) -> PlayerAdmissionDispatch:
        if isinstance(admission, CachedCompletePlayerAdmission):
            return PlayerAdmissionDispatch(
                wire_events=tuple(
                    tag_fleet_table_stream_event(event, player_id=player_id)
                    for event in admission.events
                ),
            )
        scheduled = schedule_fleet_player_run(
            scheduler,
            turn=turn,
            player_id=player_id,
            game_id=game_id,
            perspective=perspective,
            fleet_services=fleet_services,
            persistence=persistence,
            stream_token=stream_token,
        )
        if scheduled is None:
            return PlayerAdmissionDispatch(schedule_failed=True)
        return PlayerAdmissionDispatch(scheduled_player=scheduled)

    try:
        for player_id in player_ids:
            if not scheduler.owns_table_stream(stream_token):
                return

            admission = resolve_player_stream_admission(
                persistence,
                game_id=game_id,
                perspective=perspective,
                turn_number=turn_number,
                player_id=player_id,
            )
            dispatch = dispatch_player_admission(player_id, admission)
            if dispatch.schedule_failed:
                return

            yield from dispatch.wire_events

            if dispatch.scheduled_player is not None:
                controller.register_scheduled_player(player_id, dispatch.scheduled_player)
                yield from drain_available_multiplex_events(
                    controller.current_scheduled_players(),
                    tag_player_id=True,
                    finished_run_ids=controller.finished_run_ids,
                )

        if player_ids:
            try:
                yield from iter_multiplexed_fleet_table_events(
                    controller.current_scheduled_players(),
                    tag_player_id=True,
                    finished_run_ids=controller.finished_run_ids,
                    is_stream_active=lambda: scheduler.owns_table_stream(stream_token),
                    player_provider=controller.current_scheduled_players,
                    pending_events_provider=controller.drain_pending_wire_events,
                    wake_event=controller.wake_multiplex,
                )
            finally:
                cleanup_fleet_table_stream_sessions(
                    scheduler,
                    stream_scope,
                    tuple(row.session for row in controller.current_scheduled_players()),
                    stream_token=stream_token,
                )
    finally:
        controller.detach()
