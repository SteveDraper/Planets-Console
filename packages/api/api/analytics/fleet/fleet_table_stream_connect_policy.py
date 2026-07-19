"""Connect policy for one fleet table NDJSON stream."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

from api.analytics.fleet import fleet_table_stream_rows
from api.analytics.fleet.fleet_table_player_run import ScheduledFleetPlayer
from api.analytics.fleet.fleet_table_stream_controller import FleetTableStreamController
from api.analytics.fleet.fleet_table_stream_rows import (
    _TERMINAL_EVENT_TYPES,
    PlayerStreamAdmission,
    _fleet_multiplex_event_to_wire_events,
    cleanup_fleet_table_stream_sessions,
    tag_fleet_table_stream_event,
)
from api.analytics.fleet.fleet_table_stream_scheduler import FleetTableStreamScheduler
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.streaming.table_stream.connect import AdmissionDispatch


@dataclass
class FleetTableStreamConnectPolicy:
    controller: FleetTableStreamController
    scheduler: FleetTableStreamScheduler
    stream_scope: FleetTableStreamScope
    stream_token: str
    persistence: FleetSnapshotPersistenceService
    game_id: int
    perspective: int
    turn_number: int

    def preamble_events(self) -> tuple[dict[str, object], ...]:
        return ()

    def attach(self) -> None:
        self.controller.attach()

    def detach(self) -> None:
        self.controller.detach()

    def owns_table_stream(self) -> bool:
        return self.scheduler.owns_table_stream(self.stream_token)

    def resolve_admission(self, player_id: int) -> PlayerStreamAdmission:
        return fleet_table_stream_rows.resolve_player_stream_admission(
            self.persistence,
            game_id=self.game_id,
            perspective=self.perspective,
            turn_number=self.turn_number,
            player_id=player_id,
        )

    def dispatch_admission(
        self,
        player_id: int,
        admission: PlayerStreamAdmission,
    ) -> AdmissionDispatch[ScheduledFleetPlayer]:
        return self.controller.dispatch_admission(player_id, admission)

    def current_scheduled_rows(self) -> tuple[ScheduledFleetPlayer, ...]:
        return self.controller.current_scheduled_rows()

    def register_scheduled_row(self, player_id: int, scheduled: ScheduledFleetPlayer) -> None:
        self.controller.register_scheduled_row(player_id, scheduled)

    def adopt_admission_scheduled_row(
        self,
        player_id: int,
        scheduled: ScheduledFleetPlayer,
    ) -> bool:
        return self.controller.adopt_admission_scheduled_row(player_id, scheduled)

    def drain_pending_wire_events(self) -> list[dict[str, object]]:
        return self.controller.drain_pending_wire_events()

    def wake_multiplex(self) -> threading.Event:
        return self.controller.wake_multiplex

    def multiplex_event_to_wire_events(
        self,
        row: ScheduledFleetPlayer,
        raw_event: dict[str, object],
    ) -> Iterator[dict[str, object]]:
        return _fleet_multiplex_event_to_wire_events(row, raw_event)

    def tag_event(self, event: dict[str, object], player_id: int) -> dict[str, object]:
        return tag_fleet_table_stream_event(event, player_id=player_id)

    def terminal_types(self) -> frozenset[str]:
        return _TERMINAL_EVENT_TYPES

    def end_sessions(self) -> None:
        cleanup_fleet_table_stream_sessions(
            self.scheduler,
            self.stream_scope,
            tuple(row.session for row in self.controller.current_scheduled_rows()),
            stream_token=self.stream_token,
        )
