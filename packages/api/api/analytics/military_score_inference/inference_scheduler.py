"""Process-wide FIFO scheduler for inference search tier jobs."""

from __future__ import annotations

import os
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from api.analytics.military_score_inference.inference_api_payload import (
    _inference_api_payload,
    _serialize_solution_with_arithmetic,
    inference_result_to_api_payload,
)
from api.analytics.military_score_inference.inference_cancel import InferenceCancelToken
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceResult,
    InferenceSolution,
)
from api.analytics.military_score_inference.policy_ladder import (
    PolicyLadderState,
    finalize_policy_ladder_result,
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.solver import STATUS_STOPPED
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.models.game import TurnInfo
from api.transport.inference_stream import (
    inference_complete_event,
    inference_progress_event,
    inference_solution_event,
)

_DEFAULT_WORKER_COUNT = 4


def _configured_worker_count() -> int:
    raw = os.environ.get("MILITARY_SCORE_INFERENCE_SCHEDULER_WORKERS")
    if raw is not None:
        return max(1, int(raw))
    return _DEFAULT_WORKER_COUNT


@dataclass
class InferenceRowStreamSession:
    """Per-row NDJSON stream state shared between the request thread and workers."""

    player_id: int
    observation: InferenceObservation
    turn: TurnInfo
    cancel_token: InferenceCancelToken = field(default_factory=InferenceCancelToken)
    event_queue: queue.Queue[dict[str, object]] = field(default_factory=queue.Queue)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ladder_state: PolicyLadderState | None = None
    on_finalize: Callable[[dict[str, object]], None] | None = None


@dataclass(frozen=True)
class _TierJob:
    session: InferenceRowStreamSession


@dataclass(frozen=True)
class _FullRowJob:
    session: InferenceRowStreamSession
    run_inference: Callable[[InferenceRowStreamSession], dict[str, object]]


_Sentinel = object()


class InferenceRowScheduler:
    """FIFO tier-job queue drained by a shared worker pool."""

    def __init__(self, worker_count: int = _DEFAULT_WORKER_COUNT) -> None:
        self._queue: queue.Queue[_TierJob | _FullRowJob | object] = queue.Queue()
        self._sessions: dict[str, InferenceRowStreamSession] = {}
        self._lock = threading.Lock()
        self._worker_count = worker_count
        self._workers: list[threading.Thread] = []
        self._shutdown = False
        for _ in range(worker_count):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self._workers.append(thread)

    def register_session(self, session: InferenceRowStreamSession) -> None:
        with self._lock:
            self._sessions[session.run_id] = session

    def unregister_session(self, run_id: str) -> None:
        with self._lock:
            self._sessions.pop(run_id, None)

    def cancel_run(self, run_id: str) -> None:
        with self._lock:
            session = self._sessions.get(run_id)
        if session is not None:
            session.cancel_token.cancel()

    def enqueue_tier_ladder(self, session: InferenceRowStreamSession) -> None:
        policy_steps = tuple(resolve_tier_policies(None))
        session.ladder_state = PolicyLadderState(policy_steps=policy_steps)
        self.register_session(session)
        self._queue.put(_TierJob(session=session))

    def enqueue_full_row(
        self,
        session: InferenceRowStreamSession,
        run_inference: Callable[[InferenceRowStreamSession], dict[str, object]],
    ) -> None:
        self.register_session(session)
        self._queue.put(_FullRowJob(session=session, run_inference=run_inference))

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is _Sentinel:
                return
            if isinstance(job, _TierJob):
                self._run_tier_job(job.session)
            elif isinstance(job, _FullRowJob):
                self._run_full_row_job(job)

    def _emit_solution(
        self,
        session: InferenceRowStreamSession,
        solution: InferenceSolution,
    ) -> None:
        if session.ladder_state is None or session.ladder_state.catalog is None:
            return
        serialized = _serialize_solution_with_arithmetic(
            session.observation,
            session.ladder_state.catalog,
            solution,
        )
        session.event_queue.put(inference_solution_event(serialized))

    def _emit_progress(self, session: InferenceRowStreamSession) -> None:
        state = session.ladder_state
        if state is None or state.catalog is None:
            return
        session.event_queue.put(
            inference_progress_event(
                policy_step_id=state.catalog.policy_step_id,
                combo_count=len(state.catalog.ship_build_combos),
                held_count=len(state.merged_solutions),
            )
        )

    def _emit_complete_from_payload(
        self,
        session: InferenceRowStreamSession,
        payload: dict[str, object],
    ) -> None:
        session.event_queue.put(
            inference_complete_event(
                status=str(payload.get("status", "")),
                summary=str(payload.get("summary", "")),
                solution_count=int(payload.get("solutionCount", 0)),
                is_complete=bool(payload.get("isComplete", True)),
                diagnostics=(
                    payload.get("diagnostics")
                    if isinstance(payload.get("diagnostics"), dict)
                    else None
                ),
            )
        )
        self.unregister_session(session.run_id)

    def _run_tier_job(self, session: InferenceRowStreamSession) -> None:
        if session.cancel_token.is_cancelled():
            self._finalize_stopped(session)
            return
        state = session.ladder_state
        if state is None:
            return

        def on_admitted(solution: InferenceSolution) -> None:
            self._emit_solution(session, solution)

        run_policy_ladder_tier_step(
            state,
            session.observation,
            session.turn,
            time_limit_seconds=None,
            cancel_token=session.cancel_token,
            on_admitted=on_admitted,
        )
        self._emit_progress(session)

        if session.cancel_token.is_cancelled() or state.cancelled:
            self._finalize_stopped(session)
            return

        if not state.ladder_complete:
            self._queue.put(_TierJob(session=session))
            return

        self._finalize_ladder(session)

    def _finalize_ladder(self, session: InferenceRowStreamSession) -> None:
        state = session.ladder_state
        if state is None:
            return
        result, catalog, problem, policy_steps_attempted, step_diagnostics = (
            finalize_policy_ladder_result(
                state,
                session.observation,
                session.turn,
            )
        )
        payload = inference_result_to_api_payload(
            result,
            catalog,
            session.observation,
            session.turn,
            problem,
            policy_steps_attempted=policy_steps_attempted,
            step_diagnostics=step_diagnostics,
        )
        if session.on_finalize is not None:
            session.on_finalize(payload)
        self._emit_complete_from_payload(session, payload)

    def _finalize_stopped(self, session: InferenceRowStreamSession) -> None:
        state = session.ladder_state
        if state is not None and state.merged_solutions:
            result, catalog, problem, policy_steps_attempted, step_diagnostics = (
                finalize_policy_ladder_result(
                    state,
                    session.observation,
                    session.turn,
                )
            )
            stopped_result = InferenceResult(
                status=STATUS_STOPPED,
                solutions=result.solutions,
                diagnostics={**result.diagnostics, "stopped_reason": "cancelled"},
            )
            payload = inference_result_to_api_payload(
                stopped_result,
                catalog,
                session.observation,
                session.turn,
                problem,
                policy_steps_attempted=policy_steps_attempted,
                step_diagnostics=step_diagnostics,
            )
            payload["isComplete"] = True
        else:
            payload = _inference_api_payload(
                status=STATUS_STOPPED,
                summary="Build inference halted",
                solutions=(),
                diagnostics={"stopped_reason": "cancelled"},
            )
            payload["isComplete"] = True

        self._emit_complete_from_payload(session, payload)

    def _run_full_row_job(self, job: _FullRowJob) -> None:
        session = job.session
        if session.cancel_token.is_cancelled():
            self._finalize_stopped(session)
            return
        try:
            payload = job.run_inference(session)
        except Exception:
            from api.transport.inference_stream import inference_error_event

            session.event_queue.put(inference_error_event("Build inference failed"))
            self.unregister_session(session.run_id)
            return
        solutions_raw = payload.get("solutions")
        if isinstance(solutions_raw, list):
            for solution in solutions_raw:
                if isinstance(solution, dict):
                    session.event_queue.put(inference_solution_event(solution))
        self._emit_complete_from_payload(session, payload)


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
