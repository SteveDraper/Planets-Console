"""Row statuses that close scores turn evidence once they are stored.

Complete search statuses, plus stopped and time-limited. Orchestrator
tier_solve persists these rather than soft-completing the scores node with
open evidence.
"""

from __future__ import annotations

from api.analytics.military_score_inference.inference_api_payload import (
    COMPLETE_INFERENCE_SEARCH_STATUSES,
)
from api.analytics.military_score_inference.solver import (
    STATUS_STOPPED,
    STATUS_TIME_LIMITED,
)

# Once on disk, these close fleet turnEvidenceAtN.
DURABLE_TURN_EVIDENCE_ROW_STATUSES = COMPLETE_INFERENCE_SEARCH_STATUSES | frozenset(
    {STATUS_STOPPED, STATUS_TIME_LIMITED}
)


def is_durable_turn_evidence_row_status(status: str) -> bool:
    """True when persisting this row status closes scores turn evidence."""
    return status in DURABLE_TURN_EVIDENCE_ROW_STATUSES
