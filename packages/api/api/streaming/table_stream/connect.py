"""Shared connect orchestration for multiplexed table NDJSON streams."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from api.streaming.table_stream.multiplex import (
    drain_available_multiplex_events,
    iter_multiplexed_stream_events,
)


@dataclass(frozen=True)
class AdmissionDispatch:
    wire_events: tuple[dict[str, object], ...] = ()
    scheduled: object | None = None
    schedule_failed: bool = False


class TableStreamConnectPolicy(Protocol):
    def preamble_events(self) -> tuple[dict[str, object], ...]: ...

    def attach(self) -> None: ...

    def detach(self) -> None: ...

    def owns_table_stream(self) -> bool: ...

    def resolve_admission(self, player_id: int) -> object: ...

    def dispatch_admission(self, player_id: int, admission: object) -> AdmissionDispatch: ...

    def current_scheduled_rows(self) -> tuple[object, ...]: ...

    def register_scheduled_row(self, player_id: int, scheduled: object) -> None: ...

    def finished_run_ids(self) -> set[str]: ...

    def drain_pending_wire_events(self) -> list[dict[str, object]]: ...

    def wake_multiplex(self) -> threading.Event: ...

    def multiplex_event_to_wire_events(
        self,
        row: object,
        raw_event: object,
    ) -> Iterator[dict[str, object]]: ...

    def tag_event(self, event: dict[str, object], player_id: int) -> dict[str, object]: ...

    def terminal_types(self) -> frozenset[str]: ...

    def end_sessions(self) -> None: ...


def iter_table_stream_connect(
    policy: TableStreamConnectPolicy,
    player_ids: tuple[int, ...],
) -> Iterator[dict[str, object]]:
    """Admission loop, immediate yield, multiplex, and guaranteed scope teardown."""
    policy.attach()
    try:
        yield from policy.preamble_events()

        for player_id in player_ids:
            if not policy.owns_table_stream():
                return

            admission = policy.resolve_admission(player_id)
            dispatch = policy.dispatch_admission(player_id, admission)
            if dispatch.schedule_failed:
                return

            yield from dispatch.wire_events

            if dispatch.scheduled is not None:
                policy.register_scheduled_row(player_id, dispatch.scheduled)
                yield from drain_available_multiplex_events(
                    policy.current_scheduled_rows(),
                    tag_player_id=True,
                    finished_run_ids=policy.finished_run_ids(),
                    event_to_wire_events=policy.multiplex_event_to_wire_events,
                    tag_event=policy.tag_event,
                    terminal_types=policy.terminal_types(),
                )

        if player_ids:
            yield from iter_multiplexed_stream_events(
                policy.current_scheduled_rows(),
                tag_player_id=True,
                finished_run_ids=policy.finished_run_ids(),
                is_stream_active=policy.owns_table_stream,
                row_provider=policy.current_scheduled_rows,
                pending_events_provider=policy.drain_pending_wire_events,
                wake_event=policy.wake_multiplex(),
                event_to_wire_events=policy.multiplex_event_to_wire_events,
                tag_event=policy.tag_event,
                terminal_types=policy.terminal_types(),
            )
    finally:
        policy.end_sessions()
        policy.detach()


def iter_table_stream_connect_with_scope(
    *,
    begin_scope: Callable[[], str],
    on_scope_already_active: Callable[[], dict[str, object]],
    policy_factory: Callable[[str], TableStreamConnectPolicy],
    player_ids: tuple[int, ...],
) -> Iterator[dict[str, object]]:
    """Begin scheduler scope, then run shared connect orchestration."""
    from api.streaming.table_stream.errors import TableStreamScopeAlreadyActive

    try:
        stream_token = begin_scope()
    except TableStreamScopeAlreadyActive:
        yield on_scope_already_active()
        return

    policy = policy_factory(stream_token)
    yield from iter_table_stream_connect(policy, player_ids)
