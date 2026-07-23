"""Scores soft-defer / wake reason enums (leaf -- no orchestrator or scheduler imports)."""

from __future__ import annotations

from enum import StrEnum


class SoftTerminalReason(StrEnum):
    """Why scores tier solving deferred without completing the DAG node."""

    NON_DURABLE_ROW_COMPLETE = "scores_non_durable_row_complete"
    EMPTY_TIER_OUTCOME = "scores_empty_tier_outcome"
    MISSING_ROW_RUN = "scores_missing_row_run"


class ScoresWakeReason(StrEnum):
    """Publishers allowed to resume scores tier solving after a soft defer."""

    ROW_RUN_ADOPTED = "scores_row_run_adopted"
    EVIDENCE_CLOSED = "scores_evidence_closed"
    STREAM_RESCHEDULED = "scores_stream_rescheduled"
