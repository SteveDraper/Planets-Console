"""Lifecycle controller for one scores-table inference NDJSON stream."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_domain_events import (
    InferenceStreamDomainEvent,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    _TERMINAL_EVENT_TYPES,
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    RowStreamAdmission,
    ScheduledInferenceRow,
    ScheduleRowAdmission,
    resolve_row_stream_admission,
    schedule_inference_row,
    tag_inference_stream_event,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    attach_inference_table_stream,
    detach_inference_table_stream,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
)
from api.models.game import TurnInfo
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.connect import AdmissionDispatch
from api.streaming.table_stream.controller_base import TableStreamControllerBase
from api.transport.inference_stream_wire import domain_event_to_wire_events


@dataclass(kw_only=True)
class InferenceTableStreamController(
    TableStreamControllerBase[ScheduledInferenceRow, RowStreamAdmission]
):
    scope: InferenceStreamScope
    turn: TurnInfo
    scheduler: InferenceRowScheduler
    game_id: int
    perspective: int
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None
    reload_host_turn: Callable[[], TurnInfo] | None = None
    resolve_mask_for_player: Callable[[int], ResolvedHullCatalogMask | None] | None = None
    resolve_fleet_torp_resolution_for_player: (
        Callable[[int], PriorTurnFleetTorpResolution] | None
    ) = None
    export_services: Mapping[str, object] = field(default_factory=dict)
    persistence: InferenceRowPersistenceService | None = None

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
            prior_fleet_max_tech_by_axis=fleet_resolution.prior_fleet_max_tech_for_admission(),
            export_services=self.export_services,
            stream_token=self.stream_token,
        )

    def cancel_player_row(self, player_id: int) -> None:
        row = self.scheduled_rows.get(player_id)
        if row is not None:
            self.scheduler.cancel_row_run(row.session.run_id)

    def dispatch_admission(
        self,
        player_id: int,
        admission: RowStreamAdmission,
    ) -> AdmissionDispatch[ScheduledInferenceRow]:
        if isinstance(admission, ImmediateRowAdmission):
            return AdmissionDispatch(
                wire_events=tuple(
                    tag_inference_stream_event(event, player_id=player_id)
                    for event in admission.events
                ),
            )
        if isinstance(admission, CachedCompleteRowAdmission):
            if admission.event is not None:
                return AdmissionDispatch(
                    wire_events=(tag_inference_stream_event(admission.event, player_id=player_id),),
                )
            return AdmissionDispatch()
        scheduled = self.schedule_player_row(player_id)
        if scheduled is None:
            return AdmissionDispatch(schedule_failed=True)
        existing = self.scheduled_rows.get(player_id)
        if existing is not None and existing.session.run_id != scheduled.session.run_id:
            # Invalidation rescheduled during enqueue: keep the fresher row. Returning an
            # empty dispatch would still count as admitted and leave multiplex waiting on
            # zero rows (globalPause only, scheduler_runs cleared after cancel).
            self.scheduler.cancel_row_run(scheduled.session.run_id)
            if not existing.session.cancel_token.is_cancelled():
                return AdmissionDispatch(scheduled=existing)
            scheduled = existing
        if scheduled.session.cancel_token.is_cancelled():
            # Fleet persist (or other invalidation) cancelled this run before adopt and did
            # not leave a live replacement in scheduled_rows. Schedule again so connect does
            # not enter multiplex with only globalPause.
            replacement = self.schedule_player_row(player_id)
            if replacement is None or replacement.session.cancel_token.is_cancelled():
                return AdmissionDispatch(schedule_failed=True)
            return AdmissionDispatch(scheduled=replacement)
        return AdmissionDispatch(scheduled=scheduled)

    def _refresh_host_turn(self) -> None:
        if self.reload_host_turn is not None:
            self.turn = self.reload_host_turn()

    def _active_run_id_for_player(self, player_id: int) -> str | None:
        active = self.scheduler.row_run_for_player(self.scope, player_id)
        if active is None:
            return None
        return active.session.run_id

    def reschedule_row(self, player_id: int) -> bool:
        """Cancel and re-admit one row without holding ``stream_lock`` across schedule.

        ``dispatch_admission`` may ``enqueue_tier_ladder`` / ``orchestrator.submit``, and
        fleet ledger persist (or soft-defer delivery) can re-enter ``reschedule_row`` or
        ``deliver_domain_event``. Holding ``stream_lock`` across that path self-deadlocks
        on the non-reentrant lock (fleet ``reschedule_player`` parity).

        Cancel runs outside ``stream_lock``: cancel aborts orchestrator scopes and drains
        node-complete listeners that call ``deliver_domain_event`` (needs this lock).
        """
        return self.reschedule_one(
            player_id,
            cancel_run_id=self.scheduler.cancel_row_run,
            resolve_admission=self.resolve_row_admission,
            active_run_id_for_player=self._active_run_id_for_player,
            before_collect_cancels=self._refresh_host_turn,
        )

    def adopt_admission_scheduled_row(
        self,
        player_id: int,
        row: ScheduledInferenceRow,
    ) -> bool:
        return super().adopt_admission_scheduled_row(
            player_id,
            row,
            cancel_run_id=self.scheduler.cancel_row_run,
        )

    def push_admission_wire_terminal(self, session: InferenceRowStreamSession) -> bool:
        """Push immediate/cached admission wire for an empty peer complete.

        Used when ``tier_solve`` completes without a ``rowComplete`` payload but
        admission can still finish the multiplex row (skip / cached / immediate).
        Returns True when client-visible terminal wire was delivered.
        """
        admission = self.resolve_row_admission(session.player_id)
        if isinstance(admission, ScheduleRowAdmission):
            return False
        wires = list(self.dispatch_admission(session.player_id, admission).wire_events)
        if not wires:
            return False
        with self.stream_lock:
            self.pending_wire_events.extend(wires)
            stream_drain.close(session.run_id)
        self.wake_multiplex.set()
        return True

    def push_domain_event_pending_wire(
        self,
        session: InferenceRowStreamSession,
        event: InferenceStreamDomainEvent,
    ) -> None:
        """Append tagged domain-event wire to pending (drain-closed / upgrade path)."""
        with self.stream_lock:
            for wire in domain_event_to_wire_events(
                event,
                observation=session.observation,
                turn=session.turn,
                fleet_torp_input_status=session.fleet_torp_input_status,
            ):
                self.pending_wire_events.append(
                    tag_inference_stream_event(wire, player_id=session.player_id)
                )
        self.wake_multiplex.set()

    def deliver_domain_event(
        self,
        session: InferenceRowStreamSession,
        event: InferenceStreamDomainEvent,
    ) -> None:
        """Deliver a domain event to this open multiplex (bound queue or pending wire).

        Bound rows enqueue on the session queue for multiplex drain. Unbound rows
        (missed adopt / unbind) push tagged wire onto ``pending_wire_events`` so the
        connect loop still yields terminals instead of staying preamble-only.
        """
        with self.stream_lock:
            scheduled = self.scheduled_rows.get(session.player_id)
            bound = scheduled is not None and scheduled.session.run_id == session.run_id
            if bound:
                session.event_queue.put(event)
            else:
                for wire in domain_event_to_wire_events(
                    event,
                    observation=session.observation,
                    turn=session.turn,
                    fleet_torp_input_status=session.fleet_torp_input_status,
                ):
                    self.pending_wire_events.append(
                        tag_inference_stream_event(wire, player_id=session.player_id)
                    )
                    if wire.get("type") in _TERMINAL_EVENT_TYPES:
                        # Finish both the delivering session and the currently scheduled
                        # run for this player. Unbound terminals used to mark only the
                        # delivering run_id; multiplex kept waiting on the adopted
                        # session forever while the UI stayed in-progress.
                        stream_drain.close(session.run_id)
                        if scheduled is not None:
                            stream_drain.close(scheduled.session.run_id)
        self.wake_multiplex.set()

    def reschedule_all_rows(self, *, force_schedule: bool = False) -> bool:
        """Cancel and re-admit every row; schedule/submit outside ``stream_lock``."""
        return self.reschedule_all(
            cancel_run_id=self.scheduler.cancel_row_run,
            resolve_admission=lambda player_id: self.resolve_row_admission(
                player_id,
                force_schedule=force_schedule,
            ),
            before_collect_cancels=self._refresh_host_turn,
        )

    def attach(self) -> None:
        attach_inference_table_stream(self)

    def detach(self) -> None:
        detach_inference_table_stream(self.stream_token)

    def end_stream(self, scheduler: InferenceRowScheduler) -> None:
        """Detach this stream's scheduler scope while in-flight work may finish."""
        scheduler.detach_inference_stream(
            self.scope,
            tuple(row.session for row in self.current_scheduled_rows()),
            stream_token=self.stream_token,
        )
