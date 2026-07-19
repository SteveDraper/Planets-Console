"""Per-row tier ladder run state for the inference scheduler."""

from __future__ import annotations

import threading

from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.streaming.table_stream.row_run_admission import RowRunPhase


class RowRun:
    """One scoreboard row's ladder state and stream orchestration.

    ``tier_lock`` serializes ``run_inference_tier_job`` so duplicate concurrent
    ``tier_solve`` dispatches (cross-binding) cannot race ``orchestration``
    segment indexes or ladder state.

    Shell phase (``RowRunPhase``) is the generic table-stream retained-shell
    vocabulary from :mod:`api.streaming.table_stream.row_run_admission`.
    """

    def __init__(self, session: InferenceRowStreamSession) -> None:
        self.session = session
        self.ladder_state: PolicyLadderState | None = None
        self.orchestration: InferenceStreamOrchestration | None = None
        self.tier_lock = threading.RLock()
        self.phase: RowRunPhase = RowRunPhase.REGISTERED

    @property
    def run_id(self) -> str:
        return self.session.run_id
