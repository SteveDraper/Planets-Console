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
from api.transport.fleet_table_stream import fleet_error_event


@dataclass(kw_only=True)
class FleetTableStreamController(
    TableStreamControllerBase[ScheduledFleetPlayer, PlayerStreamAdmission]
):
    """Fleet table-stream controller.

    Fleet uses hard terminals only -- never soft-provisional stream resolution
    triggers or ``stream_drain.reopen_if_soft``.
    """

    scope: FleetTableStreamScope
    turn: TurnInfo
    scheduler: FleetTableStreamScheduler
    fleet_services: FleetComputeServices
    persistence: FleetSnapshotPersistenceService

    def current_scheduled_players(self) -> tuple[ScheduledFleetPlayer, ...]:
        return self.current_scheduled_rows()

    def register_scheduled_player(self, player_id: int, row: ScheduledFleetPlayer) -> None:
        self.register_scheduled_row(player_id, row)

    def dispatch_admission(
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
            return AdmissionDispatch(
                wire_events=(
                    tag_fleet_table_stream_event(
                        fleet_error_event(
                            "Fleet ledger materialization could not be scheduled",
                        ),
                        player_id=player_id,
                    ),
                ),
            )
        return AdmissionDispatch(scheduled=scheduled)

    def _active_run_id_for_player(self, player_id: int) -> str | None:
        active = self.scheduler.row_run_for_player(self.scope, player_id)
        if active is None:
            return None
        return active.session.run_id

    def _resolve_player_admission(
        self,
        player_id: int,
        *,
        force_schedule: bool = False,
    ) -> PlayerStreamAdmission:
        return resolve_player_stream_admission(
            self.persistence,
            game_id=self.fleet_services.game_id,
            perspective=self.fleet_services.perspective,
            turn_number=self.turn.settings.turn,
            player_id=player_id,
            force_schedule=force_schedule,
        )

    def reschedule_player(self, player_id: int) -> bool:
        """Cancel and re-admit one player without holding ``stream_lock`` across schedule.

        ``dispatch_admission`` may ``orchestrator.submit``, and scores persist can
        re-enter ``reschedule_player`` via invalidation. Holding ``stream_lock``
        across that path self-deadlocks (non-reentrant ``Lock``).
        """
        return self.reschedule_one(
            player_id,
            cancel_run_id=self.scheduler.cancel_player_run,
            resolve_admission=self._resolve_player_admission,
            active_run_id_for_player=self._active_run_id_for_player,
        )

    def reschedule_all_players(self, *, force_schedule: bool = False) -> bool:
        """Cancel and re-admit every player; schedule/submit outside ``stream_lock``."""
        return self.reschedule_all(
            cancel_run_id=self.scheduler.cancel_player_run,
            resolve_admission=lambda player_id: self._resolve_player_admission(
                player_id,
                force_schedule=force_schedule,
            ),
        )

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

    def adopt_admission_scheduled_row(
        self,
        player_id: int,
        row: ScheduledFleetPlayer,
    ) -> bool:
        return super().adopt_admission_scheduled_row(
            player_id,
            row,
            cancel_run_id=self.scheduler.cancel_player_run,
        )
