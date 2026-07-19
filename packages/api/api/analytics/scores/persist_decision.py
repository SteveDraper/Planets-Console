"""Single gate for scores durable persist admission."""

from __future__ import annotations

from enum import StrEnum

from api.analytics.scores.cancel_fence_store import is_run_cancel_fenced
from api.analytics.scores.known_run_allow_store import is_known_run_allowed
from api.analytics.scores.tier_row_run_registry import get_row_run


class PersistDecision(StrEnum):
    """Outcome of :func:`decide_scores_row_persist`."""

    DENY_CANCEL = "deny_cancel"
    ALLOW = "allow"
    REFUSE_UNKNOWN = "refuse_unknown"


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Decide whether a scores ``rowComplete`` persist may write.

    - ``DENY_CANCEL`` -- cancel fence or live cancel token
    - ``ALLOW`` -- live RowRun (not cancelled) or known detach allow
    - ``REFUSE_UNKNOWN`` -- no RowRun and no known allow (loud refuse)
    """
    if is_run_cancel_fenced(run_id):
        return PersistDecision.DENY_CANCEL
    run = get_row_run(run_id)
    if run is not None:
        if run.session.cancel_token.is_cancelled():
            return PersistDecision.DENY_CANCEL
        return PersistDecision.ALLOW
    if is_known_run_allowed(run_id):
        return PersistDecision.ALLOW
    return PersistDecision.REFUSE_UNKNOWN
