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
    """Lifecycle of a *retained* RowRun shell (not persist-admission memory).

    ``REGISTERED`` -- live shell indexed by scope.
    ``DETACHED`` -- stream dropped; shell retained by ``run_id`` for late persist.
    Cancel intent does not become a shell phase: the shell is dropped and compact
    cancelled-admission memory is recorded separately (see ``PersistAdmission``).
    """

    REGISTERED = "registered"
    DETACHED = "detached"


class PersistAdmission(StrEnum):
    """Persist-write admission for a scores ``run_id`` (independent of shell phase).

    ``ALLOW`` -- retained ``REGISTERED`` or ``DETACHED`` shell.
    ``CANCEL_DENY`` -- compact cancelled-admission memory (no shell).
    ``ABSENT`` -- never-seen / retired / superseded cancel.
    """

    ALLOW = "allow"
    CANCEL_DENY = "cancel_deny"
    ABSENT = "absent"


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
