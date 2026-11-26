"""Connect a table stream: claim its scope, admit and multiplex its rows, then end it.

A connect generator's ``finally`` runs when Starlette finishes iterating it (on
an anyio worker thread), when its last reference drops (often the event-loop
thread), or when the cycle collector finalizes it, on whatever thread that is.
That thread may already hold any lock a stream's end takes. So the ``finally``
does only work that is safe there: it detaches the controller from its
table-stream registry (a compare-and-swap that allocates nothing under its
lock), then posts the scheduler-side end to the scheduler's off-lock runner,
whose own thread runs it with no lock held.

This module sits above ``connect`` because the catalog bootstrap imports the
analytic registries, and those import the ``table_stream`` package, which
imports ``connect``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import partial

from api.streaming.table_stream.connect import (
    AdmissionT,
    EventT,
    ScheduledT,
    TableStreamConnectPolicy,
)
from api.streaming.table_stream.multiplex import (
    drain_available_multiplex_events,
    iter_multiplexed_stream_events,
)
from api.streaming.table_stream.registry_bootstrap import (
    ensure_table_stream_registries_registered,
)
from api.streaming.table_stream.stream_scheduler import TableStreamScheduler


def iter_table_stream_connect_with_scope[ScopeT](
    *,
    scheduler: TableStreamScheduler[ScopeT],
    scope: ScopeT,
    policy_factory: Callable[
        [str],
        TableStreamConnectPolicy[ScheduledT, AdmissionT, EventT],
    ],
    player_ids: tuple[int, ...],
) -> Iterator[dict[str, object]]:
    """Catalog the registries, claim ``scope``, then admit and multiplex the stream's rows.

    The registries are catalogued before the policy attaches its controller and
    outside every lock, so a catalog scan sees every attached controller without
    registering anything itself. The off-lock runner is started here, on the
    connect's own thread, before anything can post to it.
    """
    ensure_table_stream_registries_registered()
    scheduler.off_lock_runner.ensure_started()
    stream_token = scheduler.begin_scope(scope)
    policy: TableStreamConnectPolicy[ScheduledT, AdmissionT, EventT] | None = None
    try:
        policy = policy_factory(stream_token)
        policy.attach()
        yield from _iter_admissions_and_multiplex(policy, player_ids)
    finally:
        try:
            if policy is not None:
                policy.detach()
        finally:
            scheduler.off_lock_runner.post(partial(scheduler.end_table_stream, scope, stream_token))


def _scheduled_row_is_current(
    policy: TableStreamConnectPolicy[ScheduledT, AdmissionT, EventT],
    player_id: int,
    scheduled: ScheduledT,
) -> bool:
    scheduled_run_id = getattr(getattr(scheduled, "session", None), "run_id", None)
    if not isinstance(scheduled_run_id, str):
        return False
    for row in policy.current_scheduled_rows():
        if row.player_id != player_id:
            continue
        row_run_id = getattr(getattr(row, "session", None), "run_id", None)
        return row_run_id == scheduled_run_id
    return False


def _iter_admissions_and_multiplex(
    policy: TableStreamConnectPolicy[ScheduledT, AdmissionT, EventT],
    player_ids: tuple[int, ...],
) -> Iterator[dict[str, object]]:
    """Admission loop, immediate yield and multiplex. The caller owns attach and teardown."""
    yield from policy.preamble_events()

    admitted_player_count = 0
    deferred_submits: list[Callable[[], None]] = []
    for player_id in player_ids:
        if not policy.owns_table_stream():
            return

        admission = policy.resolve_admission(player_id)
        dispatch = policy.dispatch_admission(player_id, admission)
        if dispatch.schedule_failed:
            continue

        scheduled = dispatch.scheduled
        if scheduled is not None:
            adopted = policy.adopt_admission_scheduled_row(player_id, scheduled)
            if not adopted:
                bound_for_player = any(
                    row.player_id == player_id for row in policy.current_scheduled_rows()
                )
                if not bound_for_player:
                    # Adopt lost and nothing else is bound for this player. Do not
                    # count as admitted: that would enter multiplex with zero rows
                    # (preamble only) while scheduler work continues undrained.
                    yield from dispatch.wire_events
                    continue

        admitted_player_count += 1
        yield from dispatch.wire_events

        if dispatch.defer_submit is not None:
            deferred_submits.append(dispatch.defer_submit)
            continue

        if scheduled is not None and _scheduled_row_is_current(policy, player_id, scheduled):
            yield from drain_available_multiplex_events(
                policy.current_scheduled_rows(),
                tag_player_id=True,
                event_to_wire_events=policy.multiplex_event_to_wire_events,
                tag_event=policy.tag_event,
                terminal_types=policy.terminal_types(),
            )

    for submit in deferred_submits:
        if not policy.owns_table_stream():
            return
        submit()
        yield from drain_available_multiplex_events(
            policy.current_scheduled_rows(),
            tag_player_id=True,
            event_to_wire_events=policy.multiplex_event_to_wire_events,
            tag_event=policy.tag_event,
            terminal_types=policy.terminal_types(),
        )

    if admitted_player_count > 0 and policy.owns_table_stream():
        yield from iter_multiplexed_stream_events(
            policy.current_scheduled_rows(),
            tag_player_id=True,
            is_stream_active=policy.owns_table_stream,
            row_provider=policy.current_scheduled_rows,
            pending_events_provider=policy.drain_pending_wire_events,
            wake_event=policy.wake_multiplex(),
            event_to_wire_events=policy.multiplex_event_to_wire_events,
            tag_event=policy.tag_event,
            terminal_types=policy.terminal_types(),
        )
