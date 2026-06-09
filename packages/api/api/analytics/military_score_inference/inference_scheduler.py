"""Process-wide scheduler for inference search tier jobs."""

from __future__ import annotations

import os
import queue
import threading
from collections import deque

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
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_run import RowRun, TierJob
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.errors import ConflictError, ValidationError

_DEFAULT_WORKER_COUNT = 4
_DEQUEUE_WAIT_SECONDS = 0.25

# Re-exported for scheduler tests that construct tier jobs directly.
_TierJob = TierJob

_Sentinel = object()
_Job = TierJob | object


def _configured_worker_count() -> int:
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_SCHEDULER_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return _DEFAULT_WORKER_COUNT


class InferenceRowScheduler:
    """Fair tier-job scheduler: tier-1 jobs for all rows before any tier continuations."""

    def __init__(self, worker_count: int = _DEFAULT_WORKER_COUNT) -> None:
        # Non-continuation tier jobs (including requeued held jobs). Workers drain
        # this queue before the continuation round-robin.
        self._pending_tier_jobs: queue.Queue[TierJob] = queue.Queue()
        self._continuation_round_robin: deque[str] = deque()
        self._runs: dict[str, RowRun] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._worker_count = worker_count
        self._workers: list[threading.Thread] = []
        self._shutdown = False
        self._active_scope: InferenceStreamScope | None = None
        self._active_stream_refcount = 0
        self._globally_paused = False
        for _ in range(worker_count):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self._workers.append(thread)

    def begin_scope(self, scope: InferenceStreamScope) -> None:
        with self._condition:
            if self._active_scope == scope and self._active_stream_refcount > 0:
                raise ConflictError(
                    "An inference table stream is already active for this scope."
                )
            if self._active_scope != scope:
                self._invalidate_retained_state_locked()
                self._active_scope = scope
            self._active_stream_refcount = 1

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
            "heldJobCount": (
                sum(run.held_job_count for run in self._runs.values()) if scope_matches else 0
            ),
            "heldContinuationCount": (
                sum(run.held_continuation_count for run in self._runs.values())
                if scope_matches
                else 0
            ),
            "activeSessionCount": len(self._runs) if scope_matches else 0,
        }

    def global_pause_status(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._condition:
            return self._global_pause_status_locked(scope)

    def _require_active_stream_for_scope_locked(self, scope: InferenceStreamScope) -> None:
        if self._active_stream_refcount == 0 or self._active_scope != scope:
            raise ValidationError(
                "Global pause requires an active inference table stream for this scope."
            )

    def pause_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        """Soft pause: drain queued tier jobs; in-flight tier work is not cancelled."""
        with self._condition:
            self._require_active_stream_for_scope_locked(scope)
            if self._globally_paused:
                return self._global_pause_status_locked(scope)
            self._globally_paused = True
            self._drain_queue_locked()
            self._broadcast_global_pause_locked(paused=True)
            self._condition.notify_all()
            return self._global_pause_status_locked(scope)

    def resume_globally(self, scope: InferenceStreamScope) -> dict[str, object]:
        with self._condition:
            self._require_active_stream_for_scope_locked(scope)
            if not self._globally_paused:
                return self._global_pause_status_locked(scope)
            self._globally_paused = False
            for run in self._runs.values():
                for job in run.pop_held_jobs():
                    self._requeue_job_locked(job)
                if run.held_continuation_pending and not run.session.cancel_token.is_cancelled():
                    run.held_continuation_pending = False
                    self._enqueue_continuation_locked(run)
            self._broadcast_global_pause_locked(paused=False)
            self._condition.notify_all()
            return self._global_pause_status_locked(scope)

    def register_session(self, session: InferenceRowStreamSession) -> None:
        with self._condition:
            self._get_or_create_run(session)

    def unregister_session(self, run_id: str) -> None:
        with self._condition:
            run = self._runs.pop(run_id, None)
            if run is not None:
                run.clear_held()

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
                self._runs.pop(run_id, None)
            if self._active_scope == scope:
                self._active_stream_refcount = max(0, self._active_stream_refcount - 1)
                if self._active_stream_refcount == 0:
                    self._clear_global_pause_for_active_scope_locked(scope)
            self._condition.notify_all()

    def _clear_global_pause_for_active_scope_locked(
        self,
        scope: InferenceStreamScope,
    ) -> None:
        if self._active_scope != scope:
            return
        self._globally_paused = False
        for run in self._runs.values():
            run.clear_held()

    def cancel_run(self, run_id: str) -> None:
        with self._condition:
            run = self._runs.get(run_id)
            if run is not None:
                run.session.cancel_token.cancel()
            self._purge_queued_jobs_for_run_locked(run_id)
            self._condition.notify_all()

    def _get_or_create_run(self, session: InferenceRowStreamSession) -> RowRun:
        run = self._runs.get(session.run_id)
        if run is None:
            run = RowRun(session)
            self._runs[session.run_id] = run
        return run

    def _purge_queued_jobs_for_run_locked(self, run_id: str) -> None:
        surviving_tier_one: list[TierJob] = []
        while True:
            try:
                job = self._pending_tier_jobs.get_nowait()
            except queue.Empty:
                break
            if job.session.run_id != run_id:
                surviving_tier_one.append(job)
        for job in surviving_tier_one:
            self._pending_tier_jobs.put(job)

        run = self._runs.get(run_id)
        if run is not None:
            run.purge_queued_work()

        if self._continuation_round_robin:
            self._continuation_round_robin = deque(
                remaining_run_id
                for remaining_run_id in self._continuation_round_robin
                if remaining_run_id != run_id
            )

    def enqueue_tier_ladder(
        self,
        session: InferenceRowStreamSession,
        *,
        orchestration: InferenceStreamOrchestration | None = None,
    ) -> None:
        run = self._get_or_create_run(session)
        run.orchestration = orchestration
        if orchestration is not None:
            run.ladder_state = orchestration.new_ladder_state()
        else:
            policy_steps = tuple(resolve_tier_policies(None))
            run.ladder_state = PolicyLadderState(policy_steps=policy_steps)
        self._enqueue_job(TierJob(session=session))

    def _enqueue_job(self, job: TierJob) -> None:
        with self._condition:
            if self._globally_paused:
                self._get_or_create_run(job.session).hold_job(job)
            else:
                self._pending_tier_jobs.put(job)
            self._condition.notify_all()

    def _enqueue_continuation(self, session: InferenceRowStreamSession) -> None:
        with self._condition:
            if self._globally_paused:
                self._get_or_create_run(session).hold_continuation_signal()
            else:
                self._enqueue_continuation_locked(self._get_or_create_run(session))
            self._condition.notify_all()

    def _enqueue_continuation_locked(self, run: RowRun) -> None:
        run.enqueue_continuation()
        if len(run.continuation_jobs) == 1:
            self._continuation_round_robin.append(run.run_id)

    def _requeue_job_locked(self, job: TierJob) -> None:
        if job.is_continuation:
            run = self._get_or_create_run(job.session)
            if run.requeue_continuation(job):
                self._continuation_round_robin.append(run.run_id)
            return
        self._pending_tier_jobs.put(job)

    def _dequeue_next_job_locked(self) -> TierJob | None:
        try:
            return self._pending_tier_jobs.get_nowait()
        except queue.Empty:
            pass
        return self._dequeue_continuation_locked()

    def _dequeue_continuation_locked(self) -> TierJob | None:
        while self._continuation_round_robin:
            run_id = self._continuation_round_robin.popleft()
            run = self._runs.get(run_id)
            if run is None or not run.continuation_jobs:
                continue
            job = run.continuation_jobs.popleft()
            if run.continuation_jobs:
                self._continuation_round_robin.append(run_id)
            return job
        return None

    def _drain_queue_locked(self) -> None:
        while True:
            try:
                job = self._pending_tier_jobs.get_nowait()
            except queue.Empty:
                break
            self._get_or_create_run(job.session).hold_job(job)
        for run in self._runs.values():
            run.drain_continuations_to_held()
        self._continuation_round_robin.clear()

    def _invalidate_retained_state_locked(self) -> None:
        self._active_stream_refcount = 0
        self._globally_paused = False
        for run in list(self._runs.values()):
            run.session.cancel_token.cancel()
        self._runs.clear()
        while True:
            try:
                job = self._pending_tier_jobs.get_nowait()
            except queue.Empty:
                break
            job.session.cancel_token.cancel()
        self._continuation_round_robin.clear()

    def _broadcast_global_pause_locked(self, *, paused: bool) -> None:
        event = GlobalPauseChanged(paused=paused)
        for run in self._runs.values():
            run.session.event_queue.put(event)

    def _take_next_job(self) -> _Job | None:
        # Soft pause: globally paused workers stop dequeuing; tier jobs already
        # running in _run_tier_job continue until the current tier step finishes.
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
            if isinstance(job, TierJob):
                self._run_tier_job(job.session)

    def _emit_held_solutions(
        self,
        session: InferenceRowStreamSession,
        *,
        observation: InferenceObservation,
    ) -> None:
        run = self._runs.get(session.run_id)
        if run is None:
            return
        state = run.ladder_state
        if state is None or state.catalog is None or not state.merged_solutions:
            return
        segment_id: str | None = None
        orchestration = run.orchestration
        if orchestration is not None:
            segment = orchestration.current_segment()
            if segment is not None:
                segment_id = segment.segment_id
        session.event_queue.put(
            HeldSolutionsUpdated(
                solutions=tuple(state.merged_solutions),
                catalog=state.catalog,
                observation=observation,
                segment_id=segment_id,
            )
        )

    def _emit_progress(self, session: InferenceRowStreamSession) -> None:
        run = self._runs.get(session.run_id)
        if run is None:
            return
        state = run.ladder_state
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
        run = self._runs.get(session.run_id)
        if run is None:
            return
        state = run.ladder_state
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
        run = self._runs.get(session.run_id)
        if run is None:
            return
        # Not interrupted by global pause; merge-admit hooks may still emit solution
        # events until this tier step returns.
        callbacks = InferenceTierJobCallbacks(
            emit_tier_started_progress=lambda: self._emit_tier_started_progress(session),
            emit_progress=lambda: self._emit_progress(session),
            emit_held_solutions=lambda observation: self._emit_held_solutions(
                session,
                observation=observation,
            ),
        )
        outcome = run_inference_tier_job(run, callbacks)
        if outcome.next_ladder_state is not None:
            run.ladder_state = outcome.next_ladder_state
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
