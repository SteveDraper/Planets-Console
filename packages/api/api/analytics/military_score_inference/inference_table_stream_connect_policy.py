"""Connect policy for one scores-table inference NDJSON stream."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_domain_events import (
    InferenceStreamDomainEvent,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    _TERMINAL_EVENT_TYPES,
    RowStreamAdmission,
    ScheduledInferenceRow,
    _inference_multiplex_event_to_wire_events,
    cleanup_inference_stream_sessions,
    tag_inference_stream_event,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.streaming.table_stream.connect import AdmissionDispatch
from api.transport.inference_stream import inference_global_pause_event


@dataclass
class InferenceTableStreamConnectPolicy:
    controller: InferenceTableStreamController
    scheduler: InferenceRowScheduler
    stream_scope: InferenceStreamScope
    stream_token: str

    def preamble_events(self) -> tuple[dict[str, object], ...]:
        return (
            inference_global_pause_event(
                paused=bool(self.scheduler.global_pause_status(self.stream_scope).get("paused")),
            ),
        )

    def attach(self) -> None:
        self.controller.attach()

    def detach(self) -> None:
        self.controller.detach()

    def owns_table_stream(self) -> bool:
        return self.scheduler.owns_table_stream(self.stream_token)

    def resolve_admission(self, player_id: int) -> RowStreamAdmission:
        return self.controller.resolve_row_admission(player_id)

    def dispatch_admission(
        self,
        player_id: int,
        admission: RowStreamAdmission,
    ) -> AdmissionDispatch[ScheduledInferenceRow]:
        return self.controller.dispatch_admission(player_id, admission)

    def current_scheduled_rows(self) -> tuple[ScheduledInferenceRow, ...]:
        return self.controller.current_scheduled_rows()

    def register_scheduled_row(self, player_id: int, scheduled: ScheduledInferenceRow) -> None:
        self.controller.register_scheduled_row(player_id, scheduled)

    def finished_run_ids(self) -> set[str]:
        return self.controller.finished_run_ids

    def drain_pending_wire_events(self) -> list[dict[str, object]]:
        return self.controller.drain_pending_wire_events()

    def wake_multiplex(self) -> threading.Event:
        return self.controller.wake_multiplex

    def multiplex_event_to_wire_events(
        self,
        row: ScheduledInferenceRow,
        raw_event: InferenceStreamDomainEvent,
    ) -> Iterator[dict[str, object]]:
        return _inference_multiplex_event_to_wire_events(row, raw_event)

    def tag_event(self, event: dict[str, object], player_id: int) -> dict[str, object]:
        return tag_inference_stream_event(event, player_id=player_id)

    def terminal_types(self) -> frozenset[str]:
        return _TERMINAL_EVENT_TYPES

    def end_sessions(self) -> None:
        cleanup_inference_stream_sessions(
            self.scheduler,
            self.stream_scope,
            tuple(row.session for row in self.controller.current_scheduled_rows()),
            stream_token=self.stream_token,
        )
