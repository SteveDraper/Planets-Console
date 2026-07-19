"""Single gate for scores durable persist admission."""

from __future__ import annotations

from enum import StrEnum

from api.analytics.military_score_inference.row_run import RowRunPhase
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    is_evicted_cancelled_run,
)


class PersistDecision(StrEnum):
    """Outcome of :func:`decide_scores_row_persist`."""

    DENY_CANCEL = "deny_cancel"
    ALLOW = "allow"
    REFUSE_UNKNOWN = "refuse_unknown"


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Decide whether a scores ``rowComplete`` persist may write.

    Reads admission from the single RowRun owner (``tier_row_run_registry``):

    - ``DENY_CANCEL`` -- ``CANCELLED`` phase, shell-evicted cancel denial, or
      live cancel token
    - ``ALLOW`` -- ``REGISTERED`` or ``DETACHED``
    - ``REFUSE_UNKNOWN`` -- never-seen ``run_id`` (no shell, no cancel denial)
    """
    run = get_row_run(run_id)
    if run is None:
        if is_evicted_cancelled_run(run_id):
            return PersistDecision.DENY_CANCEL
        return PersistDecision.REFUSE_UNKNOWN
    if run.phase is RowRunPhase.CANCELLED:
        return PersistDecision.DENY_CANCEL
    if run.session.cancel_token.is_cancelled():
        return PersistDecision.DENY_CANCEL
    return PersistDecision.ALLOW
