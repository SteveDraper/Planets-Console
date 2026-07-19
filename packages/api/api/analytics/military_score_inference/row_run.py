"""Per-row tier ladder run state for the inference scheduler."""

from __future__ import annotations

import threading
from enum import StrEnum

from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState


class RowRunPhase(StrEnum):
    """Lifecycle phase for persist admission on the single RowRun owner.

    ``REGISTERED`` -- live shell; persist ALLOW.
    ``DETACHED`` -- stream dropped; shell retained; persist ALLOW.
    ``CANCELLED`` -- cancel intent; compact admission only (no shell); persist DENY.
    After persist decision or explicit retire, the registry drops the entry.
    """

    REGISTERED = "registered"
    DETACHED = "detached"
    CANCELLED = "cancelled"


class RowRun:
    """One scoreboard row's ladder state and stream orchestration.

    ``tier_lock`` serializes ``run_inference_tier_job`` so duplicate concurrent
    ``tier_solve`` dispatches (cross-binding) cannot race ``orchestration``
    segment indexes or ladder state.
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
