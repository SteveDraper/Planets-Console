"""Lifecycle controller for one scores-table inference NDJSON stream."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    RowStreamAdmission,
    ScheduledInferenceRow,
    resolve_row_stream_admission,
    schedule_inference_row,
    tag_inference_stream_event,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    attach_inference_table_stream,
    detach_inference_table_stream,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
)
from api.models.game import TurnInfo
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


@dataclass(frozen=True)
class RowAdmissionDispatch:
    wire_events: tuple[dict[str, object], ...] = ()
    scheduled_row: ScheduledInferenceRow | None = None
    schedule_failed: bool = False


@dataclass
class InferenceTableStreamController:
    scope: InferenceStreamScope
    stream_token: str
    turn: TurnInfo
    player_ids: tuple[int, ...]
    scheduler: InferenceRowScheduler
    game_id: int
    perspective: int
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None
    reload_host_turn: Callable[[], TurnInfo] | None = None
    resolve_mask_for_player: Callable[[int], ResolvedHullCatalogMask | None] | None = None
    resolve_fleet_torp_resolution_for_player: (
        Callable[[int], PriorTurnFleetTorpResolution] | None
    ) = None
    persistence: InferenceRowPersistenceService | None = None
    scheduled_rows: dict[int, ScheduledInferenceRow] = field(default_factory=dict)
    pending_wire_events: list[dict[str, object]] = field(default_factory=list)
    finished_run_ids: set[str] = field(default_factory=set)
    stream_lock: threading.Lock = field(default_factory=threading.Lock)
    wake_multiplex: threading.Event = field(default_factory=threading.Event)

    def resolve_row_admission(
        self,
        player_id: int,
        *,
        force_schedule: bool = False,
    ) -> RowStreamAdmission:
        return resolve_row_stream_admission(
            self.turn,
            player_id,
            game_id=self.game_id,
            perspective=self.perspective,
            turn_number=self.turn.settings.turn,
            load_scoreboard_turn=self.load_scoreboard_turn,
            persistence=self.persistence,
            force_schedule=force_schedule,
        )

    def schedule_player_row(self, player_id: int) -> ScheduledInferenceRow | None:
        score = next((row for row in self.turn.scores if row.ownerid == player_id), None)
        if score is None:
            return None
        resolved_mask = (
            self.resolve_mask_for_player(player_id)
            if self.resolve_mask_for_player is not None
            else None
        )
        fleet_resolution = (
            self.resolve_fleet_torp_resolution_for_player(player_id)
            if self.resolve_fleet_torp_resolution_for_player is not None
            else PriorTurnFleetTorpResolution(overlay=None, input_status="unavailable")
        )
        return schedule_inference_row(
            self.scheduler,
            score=score,
            turn=self.turn,
            player_id=player_id,
            game_id=self.game_id,
            perspective=self.perspective,
            load_scoreboard_turn=self.load_scoreboard_turn,
            resolved_mask=resolved_mask,
            fleet_torp_overlay=fleet_resolution.overlay,
            fleet_torp_input_status=fleet_resolution.input_status,
            stream_token=self.stream_token,
        )

    def cancel_player_row(self, player_id: int) -> None:
        row = self.scheduled_rows.get(player_id)
        if row is not None:
            self.scheduler.cancel_row_run(row.session.run_id)

    def current_scheduled_rows(self) -> tuple[ScheduledInferenceRow, ...]:
        with self.stream_lock:
            return tuple(self.scheduled_rows.values())

    def register_scheduled_row(self, player_id: int, row: ScheduledInferenceRow) -> None:
        with self.stream_lock:
            self.scheduled_rows[player_id] = row

    def drain_pending_wire_events(self) -> list[dict[str, object]]:
        with self.stream_lock:
            pending = self.pending_wire_events
            self.pending_wire_events = []
            return pending

    def dispatch_row_admission(
        self,
        player_id: int,
        admission: RowStreamAdmission,
    ) -> RowAdmissionDispatch:
        if isinstance(admission, ImmediateRowAdmission):
            return RowAdmissionDispatch(
                wire_events=tuple(
                    tag_inference_stream_event(event, player_id=player_id)
                    for event in admission.events
                ),
            )
        if isinstance(admission, CachedCompleteRowAdmission):
            if admission.event is not None:
                return RowAdmissionDispatch(
                    wire_events=(tag_inference_stream_event(admission.event, player_id=player_id),),
                )
            return RowAdmissionDispatch()
        scheduled = self.schedule_player_row(player_id)
        if scheduled is None:
            return RowAdmissionDispatch(schedule_failed=True)
        return RowAdmissionDispatch(scheduled_row=scheduled)

    def _register_admitted_schedule(self, player_id: int, admission: RowStreamAdmission) -> bool:
        dispatch = self.dispatch_row_admission(player_id, admission)
        if dispatch.schedule_failed:
            return False
        if dispatch.wire_events:
            self.pending_wire_events.extend(dispatch.wire_events)
        if dispatch.scheduled_row is not None:
            self.scheduled_rows[player_id] = dispatch.scheduled_row
            self.finished_run_ids.discard(dispatch.scheduled_row.session.run_id)
        return True

    def _refresh_host_turn(self) -> None:
        if self.reload_host_turn is not None:
            self.turn = self.reload_host_turn()

    def reschedule_row(self, player_id: int) -> bool:
        with self.stream_lock:
            self._refresh_host_turn()
            old_row = self.scheduled_rows.get(player_id)
            if old_row is not None:
                self.cancel_player_row(player_id)
                self.finished_run_ids.discard(old_row.session.run_id)
            self.scheduled_rows.pop(player_id, None)
            admission = self.resolve_row_admission(player_id)
            if not self._register_admitted_schedule(player_id, admission):
                return False
        self.wake_multiplex.set()
        return True

    def reschedule_all_rows(self, *, force_schedule: bool = False) -> bool:
        with self.stream_lock:
            self._refresh_host_turn()
            for player_id in self.player_ids:
                self.cancel_player_row(player_id)
            self.finished_run_ids.clear()
            self.scheduled_rows.clear()
            for player_id in self.player_ids:
                admission = self.resolve_row_admission(
                    player_id,
                    force_schedule=force_schedule,
                )
                if not self._register_admitted_schedule(player_id, admission):
                    return False
        self.wake_multiplex.set()
        return True

    def attach(self) -> None:
        attach_inference_table_stream(self)

    def detach(self) -> None:
        detach_inference_table_stream(self.stream_token)

    def end_stream(self, scheduler: InferenceRowScheduler) -> None:
        """Tear down this stream's scheduler scope (safe while the generator runs elsewhere)."""
        scheduler.end_inference_stream(
            self.scope,
            tuple(row.session for row in self.current_scheduled_rows()),
            stream_token=self.stream_token,
        )
