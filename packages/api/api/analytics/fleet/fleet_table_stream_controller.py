"""Lifecycle controller for one fleet table NDJSON stream."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.fleet_table_player_run import ScheduledFleetPlayer
from api.analytics.fleet.fleet_table_stream_registry import (
    attach_fleet_table_stream,
    detach_fleet_table_stream,
)
from api.analytics.fleet.fleet_table_stream_rows import (
    CachedCompletePlayerAdmission,
    PlayerStreamAdmission,
    resolve_player_stream_admission,
    schedule_fleet_player_run,
    tag_fleet_table_stream_event,
)
from api.analytics.fleet.fleet_table_stream_scheduler import FleetTableStreamScheduler
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo
from api.streaming.table_stream.connect import AdmissionDispatch
from api.streaming.table_stream.controller_base import TableStreamControllerBase


@dataclass(kw_only=True)
class FleetTableStreamController(TableStreamControllerBase[ScheduledFleetPlayer]):
    scope: FleetTableStreamScope
    turn: TurnInfo
    scheduler: FleetTableStreamScheduler
    fleet_services: FleetComputeServices
    persistence: FleetSnapshotPersistenceService

    def current_scheduled_players(self) -> tuple[ScheduledFleetPlayer, ...]:
        return self.current_scheduled_rows()

    def register_scheduled_player(self, player_id: int, row: ScheduledFleetPlayer) -> None:
        self.register_scheduled_row(player_id, row)

    def dispatch_player_admission(
        self,
        player_id: int,
        admission: PlayerStreamAdmission,
    ) -> AdmissionDispatch[ScheduledFleetPlayer]:
        if isinstance(admission, CachedCompletePlayerAdmission):
            return AdmissionDispatch(
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
            return AdmissionDispatch(schedule_failed=True)
        return AdmissionDispatch(scheduled=scheduled)

    def _register_admitted_schedule(self, player_id: int, admission: PlayerStreamAdmission) -> bool:
        dispatch = self.dispatch_player_admission(player_id, admission)
        if dispatch.schedule_failed:
            return False
        if dispatch.wire_events:
            self.pending_wire_events.extend(dispatch.wire_events)
        if dispatch.scheduled is not None:
            scheduled = dispatch.scheduled
            assert isinstance(scheduled, ScheduledFleetPlayer)
            self.scheduled_rows[player_id] = scheduled
            self.finished_run_ids.discard(scheduled.session.run_id)
        return True

    def reschedule_player(self, player_id: int) -> bool:
        with self.stream_lock:
            old_row = self.scheduled_rows.get(player_id)
            if old_row is not None:
                self.scheduler.cancel_player_run(old_row.session.run_id)
                self.finished_run_ids.discard(old_row.session.run_id)
            self.scheduled_rows.pop(player_id, None)
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
                old_row = self.scheduled_rows.get(player_id)
                if old_row is not None:
                    self.scheduler.cancel_player_run(old_row.session.run_id)
            self.finished_run_ids.clear()
            self.scheduled_rows.clear()
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
            tuple(row.session for row in self.current_scheduled_rows()),
            stream_token=self.stream_token,
        )
