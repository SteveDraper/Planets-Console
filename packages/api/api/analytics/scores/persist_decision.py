"""Single gate for scores durable persist admission."""

from __future__ import annotations

from enum import StrEnum

from api.analytics.military_score_inference.row_run import RowRunPhase
from api.analytics.scores.tier_row_run_registry import (
    get_row_run,
    get_row_run_phase,
)


class PersistDecision(StrEnum):
    """Outcome of :func:`decide_scores_row_persist`."""

    DENY_CANCEL = "deny_cancel"
    ALLOW = "allow"
    REFUSE_UNKNOWN = "refuse_unknown"


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Decide whether a scores ``rowComplete`` persist may write.

    Reads admission from the single RowRun owner (``tier_row_run_registry``):

    - ``DENY_CANCEL`` -- compact cancelled admission (or shell still marked cancelled)
    - ``ALLOW`` -- ``REGISTERED`` or ``DETACHED`` shell
    - ``REFUSE_UNKNOWN`` -- never-seen ``run_id`` (no shell, no cancelled admission)

    Cancel intent must go through ``apply_scores_row_cancel`` / ``mark_row_run_cancelled``;
    the live cancel token is not a persist gate.
    """
    run = get_row_run(run_id)
    if run is not None:
        if run.phase is RowRunPhase.CANCELLED:
            return PersistDecision.DENY_CANCEL
        return PersistDecision.ALLOW
    phase = get_row_run_phase(run_id)
    if phase is RowRunPhase.CANCELLED:
        return PersistDecision.DENY_CANCEL
    return PersistDecision.REFUSE_UNKNOWN
