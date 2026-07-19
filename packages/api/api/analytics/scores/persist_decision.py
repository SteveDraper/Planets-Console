"""Single gate for scores durable persist admission."""

from __future__ import annotations

from enum import StrEnum

from api.analytics.military_score_inference.row_run import PersistAdmission
from api.analytics.scores.tier_row_run_registry import get_persist_admission


class PersistDecision(StrEnum):
    """Outcome of :func:`decide_scores_row_persist`."""

    DENY_CANCEL = "deny_cancel"
    ALLOW = "allow"
    REFUSE_UNKNOWN = "refuse_unknown"


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Decide whether a scores ``rowComplete`` persist may write.

    Reads :class:`PersistAdmission` from the single RowRun owner
    (``tier_row_run_registry``):

    - ``DENY_CANCEL`` -- ``PersistAdmission.CANCEL_DENY`` (compact cancel memory)
    - ``ALLOW`` -- ``PersistAdmission.ALLOW`` (``REGISTERED`` or ``DETACHED`` shell)
    - ``REFUSE_UNKNOWN`` -- ``PersistAdmission.ABSENT`` (never-seen / retired)

    Both ``DENY_CANCEL`` and ``REFUSE_UNKNOWN`` must not write. Persist policy
    treats them as silent no-ops (never raise): cancelled late workers and
    unknown ids share the same "no durable write" contract.

    Cancel intent must go through ``apply_scores_row_cancel`` / ``mark_row_run_cancelled``;
    the live cancel token is not a persist gate. Shell ``RowRunPhase`` is not
    consulted here -- only :func:`get_persist_admission`.
    """
    admission = get_persist_admission(run_id)
    if admission is PersistAdmission.ALLOW:
        return PersistDecision.ALLOW
    if admission is PersistAdmission.CANCEL_DENY:
        return PersistDecision.DENY_CANCEL
    return PersistDecision.REFUSE_UNKNOWN
