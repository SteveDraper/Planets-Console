"""Per-row tier ladder run state for the inference scheduler."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState


class RowRun:
    """One scoreboard row's ladder state and stream orchestration."""

    def __init__(self, session: InferenceRowStreamSession) -> None:
        self.session = session
        self.ladder_state: PolicyLadderState | None = None
        self.orchestration: InferenceStreamOrchestration | None = None

    @property
    def run_id(self) -> str:
        return self.session.run_id
