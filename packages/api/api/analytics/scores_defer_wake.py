"""Scores wake reason enum (leaf -- no orchestrator or scheduler imports)."""

from __future__ import annotations

from enum import StrEnum


class ScoresWakeReason(StrEnum):
    """Publishers allowed to resume a scores tier_solve node that is waiting for its RowRun."""

    ROW_RUN_ADOPTED = "scores_row_run_adopted"
    EVIDENCE_CLOSED = "scores_evidence_closed"
    STREAM_RESCHEDULED = "scores_stream_rescheduled"
