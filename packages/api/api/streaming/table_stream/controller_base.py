"""Shared controller state for one multiplexed table NDJSON stream."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Generic, TypeVar

ScheduledT = TypeVar("ScheduledT")


@dataclass(kw_only=True)
class TableStreamControllerBase(Generic[ScheduledT]):
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
