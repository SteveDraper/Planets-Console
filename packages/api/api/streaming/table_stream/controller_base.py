"""Shared controller state for one multiplexed table NDJSON stream."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from api.streaming.table_stream.connect import AdmissionDispatch

ScheduledT = TypeVar("ScheduledT")
AdmissionT = TypeVar("AdmissionT")


@dataclass(kw_only=True)
class TableStreamControllerBase(Generic[ScheduledT, AdmissionT]):
    stream_token: str
    player_ids: tuple[int, ...]
    scheduled_rows: dict[int, ScheduledT] = field(default_factory=dict)
    pending_wire_events: list[dict[str, object]] = field(default_factory=list)
    finished_run_ids: set[str] = field(default_factory=set)
    stream_lock: threading.Lock = field(default_factory=threading.Lock)
    wake_multiplex: threading.Event = field(default_factory=threading.Event)

    def drain_pending_wire_events(self) -> list[dict[str, object]]:
        with self.stream_lock:
            pending = self.pending_wire_events
            self.pending_wire_events = []
            return pending

    def current_scheduled_rows(self) -> tuple[ScheduledT, ...]:
        with self.stream_lock:
            return tuple(self.scheduled_rows.values())

    def register_scheduled_row(self, player_id: int, row: ScheduledT) -> None:
        with self.stream_lock:
            self.scheduled_rows[player_id] = row

    def dispatch_admission(
        self,
        player_id: int,
        admission: AdmissionT,
    ) -> AdmissionDispatch[ScheduledT]:
        raise NotImplementedError

    def register_admitted_schedule(self, player_id: int, admission: AdmissionT) -> bool:
        dispatch = self.dispatch_admission(player_id, admission)
        if dispatch.schedule_failed:
            return False
        if dispatch.wire_events:
            self.pending_wire_events.extend(dispatch.wire_events)
        if dispatch.scheduled is not None:
            scheduled = dispatch.scheduled
            self.scheduled_rows[player_id] = scheduled
            self.finished_run_ids.discard(self._run_id_for_scheduled_row(scheduled))
        return True

    def _run_id_for_scheduled_row(self, row: ScheduledT) -> str:
        session = getattr(row, "session", None)
        if session is None:
            raise TypeError(f"scheduled row {row!r} has no session")
        run_id = getattr(session, "run_id", None)
        if not isinstance(run_id, str):
            raise TypeError(f"scheduled row session {session!r} has no run_id")
        return run_id
