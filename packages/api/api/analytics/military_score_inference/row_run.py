"""Per-row tier ladder run state for the inference scheduler."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState


@dataclass(frozen=True)
class TierJob:
    session: InferenceRowStreamSession
    is_continuation: bool = False


class RowRun:
    """One scoreboard row's ladder state, orchestration, queues, and held work while paused."""

    def __init__(self, session: InferenceRowStreamSession) -> None:
        self.session = session
        self.ladder_state: PolicyLadderState | None = None
        self.orchestration: InferenceStreamOrchestration | None = None
        self.continuation_jobs: deque[TierJob] = deque()
        self.held_jobs: list[TierJob] = []
        self.held_continuation_pending = False

    @property
    def run_id(self) -> str:
        return self.session.run_id

    @property
    def held_job_count(self) -> int:
        return len(self.held_jobs)

    @property
    def held_continuation_count(self) -> int:
        return 1 if self.held_continuation_pending else 0

    def enqueue_continuation(self) -> TierJob:
        job = TierJob(session=self.session, is_continuation=True)
        self.continuation_jobs.append(job)
        return job

    def requeue_continuation(self, job: TierJob) -> bool:
        """Return True when this row newly joined the continuation round-robin."""
        was_empty = not self.continuation_jobs
        self.continuation_jobs.append(job)
        return was_empty

    def hold_job(self, job: TierJob) -> None:
        self.held_jobs.append(job)

    def hold_continuation_signal(self) -> None:
        self.held_continuation_pending = True

    def drain_continuations_to_held(self) -> None:
        while self.continuation_jobs:
            self.held_jobs.append(self.continuation_jobs.popleft())

    def clear_held(self) -> None:
        self.held_jobs.clear()
        self.held_continuation_pending = False

    def pop_held_jobs(self) -> list[TierJob]:
        jobs = self.held_jobs
        self.held_jobs = []
        return jobs

    def purge_queued_work(self) -> None:
        self.continuation_jobs.clear()
        self.held_jobs.clear()
        self.held_continuation_pending = False
