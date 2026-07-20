"""Scores park / wake reason enums (leaf -- no orchestrator or scheduler imports)."""

from __future__ import annotations

from enum import StrEnum


class ScoresParkReason(StrEnum):
    """Reasons scores tier solving intentionally waits for a later wake."""

    NON_DURABLE_ROW_COMPLETE = "scores_non_durable_row_complete"
    EMPTY_TIER_OUTCOME = "scores_empty_tier_outcome"
    MISSING_ROW_RUN = "scores_missing_row_run"


class ScoresWakeReason(StrEnum):
    """Publishers allowed to resume scores tier solving after a soft park."""

    ROW_RUN_ADOPTED = "scores_row_run_adopted"
    EVIDENCE_CLOSED = "scores_evidence_closed"
    STREAM_RESCHEDULED = "scores_stream_rescheduled"
