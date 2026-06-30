"""Lifecycle controller for one fleet table NDJSON stream."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.fleet_table_player_run import ScheduledFleetPlayer
from api.analytics.fleet.fleet_table_stream_registry import (
    attach_fleet_table_stream,
    detach_fleet_table_stream,
)
from api.analytics.fleet.fleet_table_stream_rows import (
    PlayerAdmissionDispatch,
    resolve_player_stream_admission,
    schedule_fleet_player_run,
    tag_fleet_table_stream_event,
)
from api.analytics.fleet.fleet_table_stream_scheduler import FleetTableStreamScheduler
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo


@dataclass
class FleetTableStreamController:
    scope: FleetTableStreamScope
    stream_token: str
    turn: TurnInfo
    player_ids: tuple[int, ...]
    scheduler: FleetTableStreamScheduler
    fleet_services: FleetComputeServices
    persistence: FleetSnapshotPersistenceService
    scheduled_players: dict[int, ScheduledFleetPlayer] = field(default_factory=dict)
    pending_wire_events: list[dict[str, object]] = field(default_factory=list)
    finished_run_ids: set[str] = field(default_factory=set)
    stream_lock: threading.Lock = field(default_factory=threading.Lock)
    wake_multiplex: threading.Event = field(default_factory=threading.Event)

    def drain_pending_wire_events(self) -> list[dict[str, object]]:
        with self.stream_lock:
            pending = self.pending_wire_events
            self.pending_wire_events = []
            return pending

    def current_scheduled_players(self) -> tuple[ScheduledFleetPlayer, ...]:
        with self.stream_lock:
            return tuple(self.scheduled_players.values())

    def register_scheduled_player(self, player_id: int, row: ScheduledFleetPlayer) -> None:
        with self.stream_lock:
            self.scheduled_players[player_id] = row

    def _dispatch_player_admission(
        self,
        player_id: int,
        admission,
    ) -> PlayerAdmissionDispatch:
        from api.analytics.fleet.fleet_table_stream_rows import CachedCompletePlayerAdmission

        if isinstance(admission, CachedCompletePlayerAdmission):
            return PlayerAdmissionDispatch(
                wire_events=tuple(
                    tag_fleet_table_stream_event(event, player_id=player_id)
                    for event in admission.events
                ),
            )
        scheduled = schedule_fleet_player_run(
            self.scheduler,
            turn=self.turn,
            player_id=player_id,
            game_id=self.fleet_services.game_id,
            perspective=self.fleet_services.perspective,
            fleet_services=self.fleet_services,
            persistence=self.persistence,
            stream_token=self.stream_token,
        )
        if scheduled is None:
            return PlayerAdmissionDispatch(schedule_failed=True)
        return PlayerAdmissionDispatch(scheduled_player=scheduled)

    def _register_admitted_schedule(self, player_id: int, admission) -> bool:
        dispatch = self._dispatch_player_admission(player_id, admission)
        if dispatch.schedule_failed:
            return False
        if dispatch.wire_events:
            self.pending_wire_events.extend(dispatch.wire_events)
        if dispatch.scheduled_player is not None:
            self.scheduled_players[player_id] = dispatch.scheduled_player
            self.finished_run_ids.discard(dispatch.scheduled_player.session.run_id)
        return True

    def reschedule_player(self, player_id: int) -> bool:
        with self.stream_lock:
            old_row = self.scheduled_players.get(player_id)
            if old_row is not None:
                self.scheduler.cancel_player_run(old_row.session.run_id)
                self.finished_run_ids.discard(old_row.session.run_id)
            self.scheduled_players.pop(player_id, None)
            admission = resolve_player_stream_admission(
                self.persistence,
                game_id=self.fleet_services.game_id,
                perspective=self.fleet_services.perspective,
                turn_number=self.turn.settings.turn,
                player_id=player_id,
            )
            if not self._register_admitted_schedule(player_id, admission):
                return False
        self.wake_multiplex.set()
        return True

    def reschedule_all_players(self, *, force_schedule: bool = False) -> bool:
        with self.stream_lock:
            for player_id in self.player_ids:
                old_row = self.scheduled_players.get(player_id)
                if old_row is not None:
                    self.scheduler.cancel_player_run(old_row.session.run_id)
            self.finished_run_ids.clear()
            self.scheduled_players.clear()
            for player_id in self.player_ids:
                admission = resolve_player_stream_admission(
                    self.persistence,
                    game_id=self.fleet_services.game_id,
                    perspective=self.fleet_services.perspective,
                    turn_number=self.turn.settings.turn,
                    player_id=player_id,
                    force_schedule=force_schedule,
                )
                if not self._register_admitted_schedule(player_id, admission):
                    return False
        self.wake_multiplex.set()
        return True

    def attach(self) -> None:
        attach_fleet_table_stream(self)

    def detach(self) -> None:
        detach_fleet_table_stream(self.stream_token)

    def end_stream(self, scheduler: FleetTableStreamScheduler) -> None:
        scheduler.end_fleet_table_stream(
            self.scope,
            tuple(row.session for row in self.current_scheduled_players()),
            stream_token=self.stream_token,
        )
