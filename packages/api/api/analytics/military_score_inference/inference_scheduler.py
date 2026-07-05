"""Process-wide scheduler for inference search tier jobs."""

from __future__ import annotations

import os
import threading
from collections import deque
from collections.abc import Callable

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
from api.errors import ValidationError
from api.streaming.table_stream.errors import TableStreamScopeAlreadyActive
from api.streaming.table_stream.scope_guard import TableStreamScopeGuard

__all__ = ["InferenceRowScheduler", "TableStreamScopeAlreadyActive", "get_inference_row_scheduler"]

_DEFAULT_WORKER_COUNT = 4
_DEQUEUE_WAIT_SECONDS = 0.25


# Re-exported for scheduler tests that construct tier jobs directly.
_TierJob = TierJob

_Sentinel = object()
_Job = TierJob | object

OnRowCompleteCallback = Callable[[InferenceRowStreamSession, RowComplete], None]
OnHeldSolutionsUpdatedCallback = Callable[[InferenceRowStreamSession], None]


def _configured_worker_count() -> int:
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_SCHEDULER_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return _DEFAULT_WORKER_COUNT


class InferenceRowScheduler:
    """Fair tier-job scheduler: tier-1 jobs for all rows before any tier continuations."""

    def __init__(
        self,
        worker_count: int = _DEFAULT_WORKER_COUNT,
        *,
        on_row_complete: OnRowCompleteCallback | None = None,
        on_held_solutions_updated: OnHeldSolutionsUpdatedCallback | None = None,
    ) -> None:
        self._on_row_complete = on_row_complete
        self._on_held_solutions_updated = on_held_solutions_updated
        self._work_queue: deque[TierJob] = deque()
        self._runs: dict[str, RowRun] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._worker_count = worker_count
        self._workers: list[threading.Thread] = []
        self._shutdown = False
        self._scope_guard = TableStreamScopeGuard[InferenceStreamScope]()
        self._globally_paused = False
        for _ in range(worker_count):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self._workers.append(thread)

    def begin_scope(self, scope: InferenceStreamScope) -> str:
        with self._condition:
            return self._scope_guard.begin_scope_locked(
                scope,
                on_same_scope_preempt=self._preempt_active_table_stream_locked,
                on_scope_change=self._invalidate_retained_state_locked,
            )

    def owns_table_stream(self, stream_token: str) -> bool:
        with self._condition:
            return self._scope_guard.owns_table_stream_locked(stream_token)

    def active_scope_matches(self, scope: InferenceStreamScope) -> bool:
        with self._condition:
            return self._scope_guard.active_scope_matches_locked(scope)

    def row_run_for_player(
        self,
        scope: InferenceStreamScope,
        player_id: int,
    ) -> RowRun | None:
        with self._condition:
            for run in self._runs.values():
                session = run.session
                if (
                    session.game_id == scope.game_id
                    and session.perspective == scope.perspective
                    and session.turn_number == scope.turn_number
                    and session.player_id == player_id
                ):
                    return run
            return None

    def _global_pause_status_locked(self, scope: InferenceStreamScope) -> dict[str, object]:
        active_scope = self._scope_guard.active_scope
        scope_matches = active_scope == scope
        return {
            "gameId": scope.game_id,
            "perspective": scope.perspective,
            "turn": scope.turn_number,
            "paused": self._globally_paused and scope_matches,
            "activeScope": (
                {
                    "gameId": active_scope.game_id,
                    "perspective": active_scope.perspective,
                    "turn": active_scope.turn_number,
                }
                if active_scope is not None
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
        if not self._scope_guard.has_active_table_stream or self._scope_guard.active_scope != scope:
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
            self._broadcast_global_pause_locked(paused=False)
            self._condition.notify_all()
            return self._global_pause_status_locked(scope)

    def unregister_session(self, run_id: str) -> None:
        with self._condition:
            run = self._runs.pop(run_id, None)
            if run is not None:
                run.clear_held()

    def end_inference_stream(
        self,
        scope: InferenceStreamScope,
        sessions: tuple[InferenceRowStreamSession, ...],
        *,
        stream_token: str,
    ) -> None:
        """Cancel all row runs for a table stream and clear global pause on disconnect."""
        with self._condition:
            owns_scope = self._scope_guard.end_table_stream_locked(scope, stream_token)
            for session in sessions:
                run_id = session.run_id
                session.cancel_token.cancel()
                self._purge_queued_jobs_for_run_locked(run_id)
                self._runs.pop(run_id, None)
            if owns_scope:
                self._clear_global_pause_for_active_scope_locked(scope)
            self._condition.notify_all()

    def _clear_global_pause_for_active_scope_locked(
        self,
        scope: InferenceStreamScope,
    ) -> None:
        if self._scope_guard.active_scope != scope:
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
        self._work_queue = deque(job for job in self._work_queue if job.session.run_id != run_id)
        run = self._runs.get(run_id)
        if run is not None:
            run.purge_queued_work()

    def enqueue_tier_ladder(
        self,
        session: InferenceRowStreamSession,
        *,
        orchestration: InferenceStreamOrchestration | None = None,
        stream_token: str | None = None,
    ) -> None:
        with self._condition:
            if (
                stream_token is not None
                and self._scope_guard.active_table_stream_token != stream_token
            ):
                return
        run = self._get_or_create_run(session)
        run.orchestration = orchestration
        if orchestration is not None:
            run.ladder_state = orchestration.new_ladder_state(
                resolved_mask=session.resolved_mask,
                fleet_torp_overlay=session.fleet_torp_overlay,
            )
        else:
            policy_steps = tuple(resolve_tier_policies(None))
            run.ladder_state = PolicyLadderState(
                policy_steps=policy_steps,
                resolved_mask=session.resolved_mask,
                fleet_torp_overlay=session.fleet_torp_overlay,
            )
        self._enqueue_job(TierJob(session=session))

    def _enqueue_job(self, job: TierJob) -> None:
        with self._condition:
            if self._globally_paused:
                self._get_or_create_run(job.session).hold_job(job)
            else:
                self._work_queue.append(job)
            self._condition.notify_all()

    def _enqueue_continuation(self, session: InferenceRowStreamSession) -> None:
        self._enqueue_job(TierJob(session=session, is_continuation=True))

    def _requeue_job_locked(self, job: TierJob) -> None:
        self._work_queue.append(job)

    def _dequeue_next_job_locked(self) -> TierJob | None:
        if not self._work_queue:
            return None
        for index, job in enumerate(self._work_queue):
            if not job.is_continuation:
                del self._work_queue[index]
                return job
        return self._work_queue.popleft()

    def _drain_queue_locked(self) -> None:
        while self._work_queue:
            job = self._work_queue.popleft()
            self._get_or_create_run(job.session).hold_job(job)

    def _preempt_active_table_stream_locked(self) -> None:
        """Cancel in-flight row runs so a reconnect can own this scope."""
        self._globally_paused = False
        for run in list(self._runs.values()):
            run.session.cancel_token.cancel()
        self._runs.clear()
        while self._work_queue:
            job = self._work_queue.popleft()
            job.session.cancel_token.cancel()

    def _invalidate_retained_state_locked(self) -> None:
        self._preempt_active_table_stream_locked()

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
        if self._on_held_solutions_updated is not None:
            self._on_held_solutions_updated(session)

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

    def _try_claim_run_for_finalize(self, session: InferenceRowStreamSession) -> bool:
        with self._condition:
            if session.cancel_token.is_cancelled():
                return False
            run = self._runs.pop(session.run_id, None)
            if run is None:
                return False
            run.clear_held()
            return True

    def _emit_row_complete(self, session: InferenceRowStreamSession, event: RowComplete) -> None:
        if not self._try_claim_run_for_finalize(session):
            return
        if self._on_row_complete is not None:
            self._on_row_complete(session, event)
        session.event_queue.put(event)

    def cancel_row_run(self, run_id: str) -> None:
        """Cancel one row run and purge its queued tier jobs."""
        with self._condition:
            run = self._runs.get(run_id)
            if run is not None:
                run.session.cancel_token.cancel()
            self._purge_queued_jobs_for_run_locked(run_id)
            self._runs.pop(run_id, None)
            self._condition.notify_all()

    def clear_global_pause_for_scope(self, scope: InferenceStreamScope) -> None:
        with self._condition:
            if self._scope_guard.active_scope == scope:
                self._clear_global_pause_for_active_scope_locked(scope)
                self._broadcast_global_pause_locked(paused=False)
                self._condition.notify_all()

    def shutdown(self) -> None:
        """Stop worker threads; safe for test teardown after dropping a service stack."""
        with self._condition:
            self._shutdown = True
            self._invalidate_retained_state_locked()
            self._condition.notify_all()

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
        if outcome.row_complete is not None:
            self._emit_row_complete(session, outcome.row_complete)
            return
        with self._condition:
            if session.cancel_token.is_cancelled():
                return
            active_run = self._runs.get(session.run_id)
            if active_run is None:
                return
            if outcome.next_ladder_state is not None:
                active_run.ladder_state = outcome.next_ladder_state
            if outcome.enqueue_continuation:
                if self._globally_paused:
                    active_run.hold_job(TierJob(session=session, is_continuation=True))
                else:
                    self._work_queue.append(TierJob(session=session, is_continuation=True))
                self._condition.notify_all()


def create_inference_row_scheduler(
    *,
    on_row_complete: OnRowCompleteCallback | None = None,
    on_held_solutions_updated: OnHeldSolutionsUpdatedCallback | None = None,
) -> InferenceRowScheduler:
    return InferenceRowScheduler(
        worker_count=_configured_worker_count(),
        on_row_complete=on_row_complete,
        on_held_solutions_updated=on_held_solutions_updated,
    )


_scheduler: InferenceRowScheduler | None = None
_scheduler_lock = threading.Lock()


def get_inference_row_scheduler(
    *,
    on_row_complete: OnRowCompleteCallback | None = None,
    on_held_solutions_updated: OnHeldSolutionsUpdatedCallback | None = None,
) -> InferenceRowScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = create_inference_row_scheduler(
                on_row_complete=on_row_complete,
                on_held_solutions_updated=on_held_solutions_updated,
            )
        return _scheduler


def reset_inference_row_scheduler_for_tests() -> None:
    """Drop the process-wide scheduler (tests only)."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            _scheduler.shutdown()
        _scheduler = None
