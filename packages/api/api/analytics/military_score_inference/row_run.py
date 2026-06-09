"""Per-row tier ladder run state for the inference scheduler."""

from __future__ import annotations

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
    """One scoreboard row's ladder state, orchestration, and held work while paused."""

    def __init__(self, session: InferenceRowStreamSession) -> None:
        self.session = session
        self.ladder_state: PolicyLadderState | None = None
        self.orchestration: InferenceStreamOrchestration | None = None
        self.held_jobs: list[TierJob] = []

    @property
    def run_id(self) -> str:
        return self.session.run_id

    @property
    def held_job_count(self) -> int:
        return len(self.held_jobs)

    @property
    def held_continuation_count(self) -> int:
        return sum(1 for job in self.held_jobs if job.is_continuation)

    def hold_job(self, job: TierJob) -> None:
        self.held_jobs.append(job)

    def clear_held(self) -> None:
        self.held_jobs.clear()

    def pop_held_jobs(self) -> list[TierJob]:
        jobs = self.held_jobs
        self.held_jobs = []
        return jobs

    def purge_queued_work(self) -> None:
        self.held_jobs.clear()
