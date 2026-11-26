"""The connect policy a table stream supplies, and its admission dispatch type."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

ScheduledT = TypeVar("ScheduledT")
AdmissionT = TypeVar("AdmissionT")
EventT = TypeVar("EventT")


@dataclass(frozen=True)
class AdmissionDispatch(Generic[ScheduledT]):
    wire_events: tuple[dict[str, object], ...] = ()
    scheduled: ScheduledT | None = None
    schedule_failed: bool = False
    # Runs after this player's paint is yielded, and after every player's paint
    # when connect defers it. Orchestrator accept can block on a missing turn.
    defer_submit: Callable[[], None] | None = None


class TableStreamConnectPolicy(Protocol[ScheduledT, AdmissionT, EventT]):
    def preamble_events(self) -> tuple[dict[str, object], ...]: ...

    def attach(self) -> None: ...

    def detach(self) -> None: ...

    def owns_table_stream(self) -> bool: ...

    def resolve_admission(self, player_id: int) -> AdmissionT: ...

    def dispatch_admission(
        self,
        player_id: int,
        admission: AdmissionT,
    ) -> AdmissionDispatch[ScheduledT]: ...

    def current_scheduled_rows(self) -> tuple[ScheduledT, ...]: ...

    def register_scheduled_row(self, player_id: int, scheduled: ScheduledT) -> None: ...

    def adopt_admission_scheduled_row(self, player_id: int, scheduled: ScheduledT) -> bool: ...

    def drain_pending_wire_events(self) -> list[dict[str, object]]: ...

    def wake_multiplex(self) -> threading.Event: ...

    def multiplex_event_to_wire_events(
        self,
        row: ScheduledT,
        raw_event: EventT,
    ) -> Iterator[dict[str, object]]: ...

    def tag_event(self, event: dict[str, object], player_id: int) -> dict[str, object]: ...

    def terminal_types(self) -> frozenset[str]: ...
