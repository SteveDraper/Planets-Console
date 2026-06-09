"""Process-wide scheduler for inference search tier jobs."""

from __future__ import annotations

import os
import queue
import threading
from collections import deque
from dataclasses import dataclass

from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    GlobalPauseChanged,
    HeldSolutionsUpdated,
    RowComplete,
    TierProgress,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.policy_ladder import PolicyLadderState
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies

_DEFAULT_WORKER_COUNT = 4
_DEQUEUE_WAIT_SECONDS = 0.25


def _configured_worker_count() -> int:
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_SCHEDULER_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return _DEFAULT_WORKER_COUNT


@dataclass(frozen=True)
class _TierJob:
    session: InferenceRowStreamSession
    is_continuation: bool = False


_Sentinel = object()
_Job = _TierJob | object


class InferenceRowScheduler:
    """Fair tier-job scheduler: tier-1 jobs for all rows before any tier continuations."""

    def __init__(self, worker_count: int = _DEFAULT_WORKER_COUNT) -> None:
        self._tier_one_queue: queue.Queue[_TierJob] = queue.Queue()
        self._continuation_by_run: dict[str, deque[_TierJob]] = {}
        self._continuation_round_robin: deque[str] = deque()
        self._sessions: dict[str, InferenceRowStreamSession] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._worker_count = worker_count
        self._workers: list[threading.Thread] = []
        self._shutdown = False
        self._active_scope: InferenceStreamScope | None = None
        self._globally_paused = False
        self._held_jobs: list[_TierJob] = []
        self._held_continuations: dict[str, InferenceRowStreamSession] = {}
        for _ in range(worker_count):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self._workers.append(thread)

    def begin_scope(self, scope: InferenceStreamScope) -> None:
        with self._condition:
            if self._active_scope != scope:
                self._invalidate_retained_state_locked()
                self._active_scope = scope

    def _global_pause_status_locked(self, scope: InferenceStreamScope) -> dict[str, object]:
        scope_matches = self._active_scope == scope
        return {
            "gameId": scope.game_id,
            "perspective": scope.perspective,
            "turn": scope.turn_number,
            "paused": self._globally_paused and scope_matches,
            "activeScope": (
                {
                    "gameId": self._active_scope.game_id,
                    "perspective": self._active_scope.perspective,
                    "turn": self._active_scope.turn_number,
                }
                if self._active_scope is not None
                else None
            ),
            "heldJobCount": len(self._held_jobs) if scope_matches else 0,
            "heldContinuationCount": len(self._held_continuations) if scope_matches else 0,
            "activeSessionCount": len(self._sessions) if scope_matches else 0,
        }

    def global_pause_status(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._condition:
            return self._global_pause_status_locked(scope)

    def pause_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._condition:
            if self._active_scope is not None and self._active_scope != scope:
                self._invalidate_retained_state_locked()
            self._active_scope = scope
            if self._globally_paused:
                return self._global_pause_status_locked(scope)
            self._globally_paused = True
            self._drain_queue_locked()
            self._broadcast_global_pause_locked(paused=True)
            self._condition.notify_all()
            return self._global_pause_status_locked(scope)

    def resume_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._condition:
            if self._active_scope != scope:
                return self._global_pause_status_locked(scope)
            if not self._globally_paused:
                return self._global_pause_status_locked(scope)
            self._globally_paused = False
            for job in self._held_jobs:
                self._requeue_job_locked(job)
            self._held_jobs.clear()
            for session in self._held_continuations.values():
                if not session.cancel_token.is_cancelled():
                    self._enqueue_continuation_locked(session)
            self._held_continuations.clear()
            self._broadcast_global_pause_locked(paused=False)
            self._condition.notify_all()
            return self._global_pause_status_locked(scope)

    def register_session(self, session: InferenceRowStreamSession) -> None:
        with self._condition:
            self._sessions[session.run_id] = session

    def unregister_session(self, run_id: str) -> None:
        with self._condition:
            self._sessions.pop(run_id, None)
            self._held_continuations.pop(run_id, None)

    def end_inference_stream(
        self,
        scope: InferenceStreamScope,
        sessions: tuple[InferenceRowStreamSession, ...],
    ) -> None:
        """Cancel all row runs for a table stream and clear global pause on disconnect."""
        with self._condition:
            for session in sessions:
                run_id = session.run_id
                session.cancel_token.cancel()
                self._purge_queued_jobs_for_run_locked(run_id)
                self._held_continuations.pop(run_id, None)
                self._sessions.pop(run_id, None)
            self._clear_global_pause_for_active_scope_locked(scope)
            self._condition.notify_all()

    def _clear_global_pause_for_active_scope_locked(
        self,
        scope: InferenceStreamScope,
    ) -> None:
        if self._active_scope != scope:
            return
        self._globally_paused = False
        self._held_jobs.clear()
        self._held_continuations.clear()

    def cancel_run(self, run_id: str) -> None:
        with self._condition:
            session = self._sessions.get(run_id)
            if session is not None:
                session.cancel_token.cancel()
            self._purge_queued_jobs_for_run_locked(run_id)
            self._held_continuations.pop(run_id, None)
            self._condition.notify_all()

    def _purge_queued_jobs_for_run_locked(self, run_id: str) -> None:
        surviving_tier_one: list[_TierJob] = []
        while True:
            try:
                job = self._tier_one_queue.get_nowait()
            except queue.Empty:
                break
            if job.session.run_id != run_id:
                surviving_tier_one.append(job)
        for job in surviving_tier_one:
            self._tier_one_queue.put(job)

        self._continuation_by_run.pop(run_id, None)
        if self._continuation_round_robin:
            self._continuation_round_robin = deque(
                remaining_run_id
                for remaining_run_id in self._continuation_round_robin
                if remaining_run_id != run_id
            )

        self._held_jobs = [job for job in self._held_jobs if job.session.run_id != run_id]

    def enqueue_tier_ladder(
        self,
        session: InferenceRowStreamSession,
        *,
        orchestration: InferenceStreamOrchestration | None = None,
    ) -> None:
        session.orchestration = orchestration
        if orchestration is not None:
            session.ladder_state = orchestration.new_ladder_state()
        else:
            policy_steps = tuple(resolve_tier_policies(None))
            session.ladder_state = PolicyLadderState(policy_steps=policy_steps)
        self.register_session(session)
        self._enqueue_job(_TierJob(session=session))

    def _enqueue_job(self, job: _TierJob) -> None:
        with self._condition:
            if self._globally_paused:
                self._held_jobs.append(job)
            else:
                self._tier_one_queue.put(job)
            self._condition.notify_all()

    def _enqueue_continuation(self, session: InferenceRowStreamSession) -> None:
        with self._condition:
            if self._globally_paused:
                self._held_continuations[session.run_id] = session
            else:
                self._enqueue_continuation_locked(session)
            self._condition.notify_all()

    def _enqueue_continuation_locked(self, session: InferenceRowStreamSession) -> None:
        job = _TierJob(session=session, is_continuation=True)
        run_id = session.run_id
        row_queue = self._continuation_by_run.setdefault(run_id, deque())
        if not row_queue:
            self._continuation_round_robin.append(run_id)
        row_queue.append(job)

    def _requeue_job_locked(self, job: _TierJob) -> None:
        if job.is_continuation:
            self._enqueue_continuation_locked(job.session)
            return
        self._tier_one_queue.put(job)

    def _dequeue_next_job_locked(self) -> _TierJob | None:
        try:
            return self._tier_one_queue.get_nowait()
        except queue.Empty:
            pass
        return self._dequeue_continuation_locked()

    def _dequeue_continuation_locked(self) -> _TierJob | None:
        while self._continuation_round_robin:
            run_id = self._continuation_round_robin.popleft()
            row_queue = self._continuation_by_run.get(run_id)
            if row_queue is None or not row_queue:
                self._continuation_by_run.pop(run_id, None)
                continue
            job = row_queue.popleft()
            if row_queue:
                self._continuation_round_robin.append(run_id)
            else:
                self._continuation_by_run.pop(run_id, None)
            return job
        return None

    def _drain_queue_locked(self) -> None:
        while True:
            try:
                job = self._tier_one_queue.get_nowait()
            except queue.Empty:
                break
            self._held_jobs.append(job)
        for run_id in list(self._continuation_by_run):
            row_queue = self._continuation_by_run.pop(run_id, None)
            if row_queue is None:
                continue
            while row_queue:
                self._held_jobs.append(row_queue.popleft())
        self._continuation_round_robin.clear()

    def _invalidate_retained_state_locked(self) -> None:
        self._globally_paused = False
        for session in list(self._sessions.values()):
            session.cancel_token.cancel()
        self._sessions.clear()
        self._held_jobs.clear()
        self._held_continuations.clear()
        while True:
            try:
                job = self._tier_one_queue.get_nowait()
            except queue.Empty:
                break
            job.session.cancel_token.cancel()
        for run_id in list(self._continuation_by_run):
            row_queue = self._continuation_by_run.pop(run_id, None)
            if row_queue is None:
                continue
            while row_queue:
                row_queue.popleft().session.cancel_token.cancel()
        self._continuation_round_robin.clear()

    def _broadcast_global_pause_locked(self, *, paused: bool) -> None:
        event = GlobalPauseChanged(paused=paused)
        for session in self._sessions.values():
            session.event_queue.put(event)

    def _take_next_job(self) -> _Job | None:
        with self._condition:
            while not self._shutdown:
                if not self._globally_paused:
                    job = self._dequeue_next_job_locked()
                    if job is not None:
                        return job
                self._condition.wait(timeout=_DEQUEUE_WAIT_SECONDS)
            return _Sentinel

    def _worker_loop(self) -> None:
        while True:
            job = self._take_next_job()
            if job is None:
                continue
            if job is _Sentinel:
                return
            if isinstance(job, _TierJob):
                self._run_tier_job(job.session)

    def _emit_held_solutions(
        self,
        session: InferenceRowStreamSession,
        *,
        observation: InferenceObservation,
    ) -> None:
        state = session.ladder_state
        if state is None or state.catalog is None or not state.merged_solutions:
            return
        session.event_queue.put(
            HeldSolutionsUpdated(
                solutions=tuple(state.merged_solutions),
                catalog=state.catalog,
                observation=observation,
            )
        )

    def _emit_progress(self, session: InferenceRowStreamSession) -> None:
        state = session.ladder_state
        if state is None or state.catalog is None:
            return
        session.event_queue.put(
            TierProgress(
                policy_step_id=state.catalog.policy_step_id,
                combo_count=len(state.catalog.ship_build_combos),
                held_count=len(state.merged_solutions),
            )
        )

    def _emit_tier_started_progress(self, session: InferenceRowStreamSession) -> None:
        state = session.ladder_state
        if state is None or state.next_step_index >= len(state.policy_steps):
            return
        step = state.policy_steps[state.next_step_index]
        session.event_queue.put(
            TierProgress(
                policy_step_id=step.id,
                held_count=len(state.merged_solutions),
            )
        )

    def _emit_row_complete(self, session: InferenceRowStreamSession, event: RowComplete) -> None:
        session.event_queue.put(event)
        self.unregister_session(session.run_id)

    def _run_tier_job(self, session: InferenceRowStreamSession) -> None:
        callbacks = InferenceTierJobCallbacks(
            emit_tier_started_progress=lambda: self._emit_tier_started_progress(session),
            emit_progress=lambda: self._emit_progress(session),
            emit_held_solutions=lambda observation: self._emit_held_solutions(
                session,
                observation=observation,
            ),
        )
        outcome = run_inference_tier_job(session, callbacks)
        if outcome.next_ladder_state is not None:
            session.ladder_state = outcome.next_ladder_state
        if outcome.enqueue_continuation:
            self._enqueue_continuation(session)
            return
        if outcome.row_complete is not None:
            self._emit_row_complete(session, outcome.row_complete)


_scheduler: InferenceRowScheduler | None = None
_scheduler_lock = threading.Lock()


def get_inference_row_scheduler() -> InferenceRowScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = InferenceRowScheduler(worker_count=_configured_worker_count())
        return _scheduler


def reset_inference_row_scheduler_for_tests() -> None:
    """Drop the process-wide scheduler (tests only)."""
    global _scheduler
    with _scheduler_lock:
        _scheduler = None
