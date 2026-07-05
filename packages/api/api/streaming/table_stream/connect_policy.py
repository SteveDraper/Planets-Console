"""Shared TableStreamConnectPolicy delegation from a controller plus hooks."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

from api.streaming.table_stream.connect import AdmissionDispatch

ScheduledT = TypeVar("ScheduledT")


class TableStreamConnectController(Protocol[ScheduledT]):
    def attach(self) -> None: ...

    def detach(self) -> None: ...

    def current_scheduled_rows(self) -> tuple[ScheduledT, ...]: ...

    def register_scheduled_row(self, player_id: int, scheduled: ScheduledT) -> None: ...

    def drain_pending_wire_events(self) -> list[dict[str, object]]: ...

    finished_run_ids: set[str]
    wake_multiplex: threading.Event


@dataclass
class TableStreamConnectPolicyHooks(Generic[ScheduledT]):
    resolve_admission: Callable[[int], object]
    dispatch_admission: Callable[[int, object], AdmissionDispatch]
    multiplex_event_to_wire_events: Callable[[ScheduledT, object], Iterator[dict[str, object]]]
    tag_event: Callable[[dict[str, object], int], dict[str, object]]
    terminal_types: Callable[[], frozenset[str]]
    end_sessions: Callable[[], None]
    preamble_events: Callable[[], tuple[dict[str, object], ...]] = lambda: ()


@dataclass
class DelegatingTableStreamConnectPolicy(Generic[ScheduledT]):
    controller: TableStreamConnectController[ScheduledT]
    owns_table_stream_fn: Callable[[], bool]
    hooks: TableStreamConnectPolicyHooks[ScheduledT]

    def preamble_events(self) -> tuple[dict[str, object], ...]:
        return self.hooks.preamble_events()

    def attach(self) -> None:
        self.controller.attach()

    def detach(self) -> None:
        self.controller.detach()

    def owns_table_stream(self) -> bool:
        return self.owns_table_stream_fn()

    def resolve_admission(self, player_id: int) -> object:
        return self.hooks.resolve_admission(player_id)

    def dispatch_admission(self, player_id: int, admission: object) -> AdmissionDispatch:
        return self.hooks.dispatch_admission(player_id, admission)

    def current_scheduled_rows(self) -> tuple[ScheduledT, ...]:
        return self.controller.current_scheduled_rows()

    def register_scheduled_row(self, player_id: int, scheduled: object) -> None:
        self.controller.register_scheduled_row(player_id, cast(ScheduledT, scheduled))

    def finished_run_ids(self) -> set[str]:
        return self.controller.finished_run_ids

    def drain_pending_wire_events(self) -> list[dict[str, object]]:
        return self.controller.drain_pending_wire_events()

    def wake_multiplex(self) -> threading.Event:
        return self.controller.wake_multiplex

    def multiplex_event_to_wire_events(
        self,
        row: object,
        raw_event: object,
    ) -> Iterator[dict[str, object]]:
        return self.hooks.multiplex_event_to_wire_events(cast(ScheduledT, row), raw_event)

    def tag_event(self, event: dict[str, object], player_id: int) -> dict[str, object]:
        return self.hooks.tag_event(event, player_id)

    def terminal_types(self) -> frozenset[str]:
        return self.hooks.terminal_types()

    def end_sessions(self) -> None:
        self.hooks.end_sessions()
