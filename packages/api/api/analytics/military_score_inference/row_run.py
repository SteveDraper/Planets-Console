"""Per-row tier ladder run state for the inference scheduler."""

from __future__ import annotations

import threading

from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.tier_ladder import LadderRebuild, TierLadder
from api.streaming.table_stream.row_run_admission import RowRunPhase


class RowRun:
    """One scoreboard row's tier ladder and the stream session it reports to.

    ``tier_lock`` serializes ``run_inference_tier_job`` so duplicate concurrent
    ``tier_solve`` dispatches (cross-binding) cannot race the ladder's segment
    indexes or ladder state.

    Shell phase (``RowRunPhase``) is the generic table-stream retained-shell
    vocabulary from :mod:`api.streaming.table_stream.row_run_admission`.

    A run always has a ladder (:class:`TierLadder`), replaced as a whole value.
    Production builds runs through
    :func:`api.analytics.scores.tier_row_run_registry.new_tier_row_run`, which
    seeds the ladder from the session.
    """

    def __init__(self, session: InferenceRowStreamSession, *, ladder: TierLadder) -> None:
        self.session = session
        self.ladder = ladder
        # Written by a ladder claim under the registry lock; taken, through the
        # registry, by the next tier step under ``tier_lock``.
        self.pending_rebuild: LadderRebuild | None = None
        self.tier_lock = threading.RLock()
        self.phase: RowRunPhase = RowRunPhase.REGISTERED

    @property
    def run_id(self) -> str:
        return self.session.run_id
