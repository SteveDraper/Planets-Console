"""Fleet table NDJSON stream helpers: player scheduling, multiplexing, and lifecycle."""

from __future__ import annotations

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
    get_fleet_table_stream_scheduler,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo
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

_TERMINAL_EVENT_TYPES = frozenset({"complete", "error"})


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


def _fleet_multiplex_event_to_wire_events(
    row: ScheduledFleetPlayer,
    raw_event: dict[str, object],
) -> Iterator[dict[str, object]]:
    yield raw_event


def drain_available_multiplex_events(
    players: tuple[ScheduledFleetPlayer, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str],
) -> Iterator[dict[str, object]]:
    """Yield any events already queued without blocking."""
    return _drain_available_multiplex_events(
        players,
        tag_player_id=tag_player_id,
        finished_run_ids=finished_run_ids,
        event_to_wire_events=_fleet_multiplex_event_to_wire_events,
        tag_event=lambda event, player_id: tag_fleet_table_stream_event(
            event,
            player_id=player_id,
        ),
        terminal_types=_TERMINAL_EVENT_TYPES,
    )


def iter_multiplexed_fleet_table_events(
    players: tuple[ScheduledFleetPlayer, ...],
    *,
    tag_player_id: bool,
    finished_run_ids: set[str] | None = None,
    is_stream_active: Callable[[], bool] | None = None,
    player_provider: Callable[[], tuple[ScheduledFleetPlayer, ...]] | None = None,
    pending_events_provider: Callable[[], list[dict[str, object]]] | None = None,
    wake_event: object | None = None,
) -> Iterator[dict[str, object]]:
    """Round-robin blocking reads across player event queues until players finish."""
    return iter_multiplexed_stream_events(
        players,
        tag_player_id=tag_player_id,
        finished_run_ids=finished_run_ids,
        is_stream_active=is_stream_active,
        row_provider=player_provider,
        pending_events_provider=pending_events_provider,
        wake_event=wake_event,
        event_to_wire_events=_fleet_multiplex_event_to_wire_events,
        tag_event=lambda event, player_id: tag_fleet_table_stream_event(
            event,
            player_id=player_id,
        ),
        terminal_types=_TERMINAL_EVENT_TYPES,
    )


def cleanup_fleet_table_stream_sessions(
    scheduler: FleetTableStreamScheduler,
    scope: FleetTableStreamScope,
    sessions: tuple[FleetPlayerStreamSession, ...],
    *,
    stream_token: str,
) -> None:
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
    resolved_scheduler = scheduler or get_fleet_table_stream_scheduler()

    def policy_factory(
        stream_token: str,
    ) -> DelegatingTableStreamConnectPolicy[
        ScheduledFleetPlayer,
        PlayerStreamAdmission,
        dict[str, object],
    ]:
        controller = FleetTableStreamController(
            scope=stream_scope,
            stream_token=stream_token,
            turn=turn,
            player_ids=player_ids,
            scheduler=resolved_scheduler,
            fleet_services=fleet_services,
            persistence=persistence,
        )
        return DelegatingTableStreamConnectPolicy(
            controller=controller,
            owns_table_stream_fn=lambda: resolved_scheduler.owns_table_stream(stream_token),
            hooks=TableStreamConnectPolicyHooks(
                resolve_admission=lambda player_id: resolve_player_stream_admission(
                    persistence,
                    game_id=game_id,
                    perspective=perspective,
                    turn_number=turn_number,
                    player_id=player_id,
                ),
                dispatch_admission=controller.dispatch_player_admission,
                multiplex_event_to_wire_events=_fleet_multiplex_event_to_wire_events,
                tag_event=lambda event, player_id: tag_fleet_table_stream_event(
                    event,
                    player_id=player_id,
                ),
                terminal_types=lambda: _TERMINAL_EVENT_TYPES,
                end_sessions=lambda: cleanup_fleet_table_stream_sessions(
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
