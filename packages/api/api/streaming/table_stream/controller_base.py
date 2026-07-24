"""Shared controller state for one multiplexed table NDJSON stream.

Lock invariant
--------------
Never hold ``stream_lock`` across cancel, ``dispatch_admission``, schedule, or
orchestrator submit/drain. Those paths may re-enter the controller (invalidation
→ reschedule, domain-event delivery) and ``stream_lock`` is not reentrant.

Safe choreography (see ``reschedule_one`` / ``reschedule_all`` /
``install_admission_dispatch``):

1. Under lock: snapshot cancel targets / clear scheduled rows; optional refresh.
2. Outside lock: cancel runs, resolve admission, ``dispatch_admission`` (schedule).
3. Under lock again: install wires/scheduled via ``install_admission_dispatch``;
   cancel raced schedules outside the lock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
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

    def adopt_admission_scheduled_row(
        self,
        player_id: int,
        row: ScheduledT,
        *,
        cancel_run_id: Callable[[str], None],
    ) -> bool:
        """Register connect admission unless invalidation rescheduled during enqueue.

        Returns False when a fresher row is already registered for ``player_id``.
        """
        with self.stream_lock:
            existing = self.scheduled_rows.get(player_id)
            new_run_id = self._run_id_for_scheduled_row(row)
            cancel_token = getattr(getattr(row, "session", None), "cancel_token", None)
            is_cancelled = getattr(cancel_token, "is_cancelled", None)
            if callable(is_cancelled) and bool(is_cancelled()):
                # Invalidation cancelled this connect-enqueued run before adopt; keep any
                # fresher row already registered and do not resurrect the cancelled one.
                return False
            if existing is not None:
                existing_run_id = self._run_id_for_scheduled_row(existing)
                if existing_run_id != new_run_id:
                    cancel_run_id(new_run_id)
                    return False
            self.scheduled_rows[player_id] = row
            return True

    def dispatch_admission(
        self,
        player_id: int,
        admission: AdmissionT,
    ) -> AdmissionDispatch[ScheduledT]:
        raise NotImplementedError

    def register_admitted_schedule(self, player_id: int, admission: AdmissionT) -> bool:
        """Legacy helper: dispatch then mutate scheduled/pending **without** ``stream_lock``.

        Connect uses ``dispatch_admission`` + ``adopt_admission_scheduled_row`` instead.
        Reschedule paths must use ``reschedule_one`` / ``reschedule_all`` (cancel and
        schedule outside the lock; install via ``install_admission_dispatch``).

        Do **not** call this while holding ``stream_lock``, and do not use it from
        reschedule: ``dispatch_admission`` may schedule/submit and re-enter the
        controller, which deadlocks on the non-reentrant lock.
        """
        dispatch = self.dispatch_admission(player_id, admission)
        if dispatch.schedule_failed:
            return False
        if dispatch.wire_events:
            self.pending_wire_events.extend(dispatch.wire_events)
        if dispatch.scheduled is not None:
            self.scheduled_rows[player_id] = dispatch.scheduled
        return True

    def install_admission_dispatch(
        self,
        player_id: int,
        dispatch: AdmissionDispatch[ScheduledT],
        *,
        cancel_run_id: Callable[[str], None],
    ) -> bool:
        """Apply one admission result under ``stream_lock``; cancel raced schedules."""
        raced_run_id: str | None = None
        with self.stream_lock:
            if player_id in self.scheduled_rows:
                if dispatch.scheduled is not None:
                    raced_run_id = self._run_id_for_scheduled_row(dispatch.scheduled)
            else:
                if dispatch.wire_events:
                    self.pending_wire_events.extend(dispatch.wire_events)
                if dispatch.scheduled is not None:
                    self.scheduled_rows[player_id] = dispatch.scheduled
        if raced_run_id is not None:
            cancel_run_id(raced_run_id)
        self.wake_multiplex.set()
        return True

    def reschedule_one(
        self,
        player_id: int,
        *,
        cancel_run_id: Callable[[str], None],
        resolve_admission: Callable[[int], AdmissionT],
        active_run_id_for_player: Callable[[int], str | None] | None = None,
        before_collect_cancels: Callable[[], None] | None = None,
    ) -> bool:
        """Cancel and re-admit one player without holding ``stream_lock`` across schedule."""
        cancel_run_ids: list[str] = []
        with self.stream_lock:
            if before_collect_cancels is not None:
                before_collect_cancels()
            old_row = self.scheduled_rows.get(player_id)
            if old_row is not None:
                cancel_run_ids.append(self._run_id_for_scheduled_row(old_row))
                self.scheduled_rows.pop(player_id, None)
            elif active_run_id_for_player is not None:
                active_run_id = active_run_id_for_player(player_id)
                if active_run_id is not None:
                    cancel_run_ids.append(active_run_id)
        for run_id in cancel_run_ids:
            cancel_run_id(run_id)
        with self.stream_lock:
            if player_id in self.scheduled_rows:
                self.wake_multiplex.set()
                return True
        admission = resolve_admission(player_id)
        dispatch = self.dispatch_admission(player_id, admission)
        if dispatch.schedule_failed:
            return False
        return self.install_admission_dispatch(
            player_id,
            dispatch,
            cancel_run_id=cancel_run_id,
        )

    def reschedule_all(
        self,
        *,
        cancel_run_id: Callable[[str], None],
        resolve_admission: Callable[[int], AdmissionT],
        before_collect_cancels: Callable[[], None] | None = None,
    ) -> bool:
        """Cancel and re-admit every player; schedule/submit outside ``stream_lock``."""
        cancel_run_ids: list[str] = []
        with self.stream_lock:
            if before_collect_cancels is not None:
                before_collect_cancels()
            for player_id in self.player_ids:
                old_row = self.scheduled_rows.get(player_id)
                if old_row is not None:
                    cancel_run_ids.append(self._run_id_for_scheduled_row(old_row))
            self.scheduled_rows.clear()
        for run_id in cancel_run_ids:
            cancel_run_id(run_id)

        dispatches: list[tuple[int, AdmissionDispatch[ScheduledT]]] = []
        for player_id in self.player_ids:
            admission = resolve_admission(player_id)
            dispatch = self.dispatch_admission(player_id, admission)
            if dispatch.schedule_failed:
                for _, prior in dispatches:
                    if prior.scheduled is not None:
                        cancel_run_id(self._run_id_for_scheduled_row(prior.scheduled))
                return False
            dispatches.append((player_id, dispatch))

        for player_id, dispatch in dispatches:
            if not self.install_admission_dispatch(
                player_id,
                dispatch,
                cancel_run_id=cancel_run_id,
            ):
                return False
        return True

    def _run_id_for_scheduled_row(self, row: ScheduledT) -> str:
        session = getattr(row, "session", None)
        if session is None:
            raise TypeError(f"scheduled row {row!r} has no session")
        run_id = getattr(session, "run_id", None)
        if not isinstance(run_id, str):
            raise TypeError(f"scheduled row session {session!r} has no run_id")
        return run_id
