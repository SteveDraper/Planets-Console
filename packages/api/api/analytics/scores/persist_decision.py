"""Single production gate for scores durable persist admission."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.scores.tier_row_run_registry import get_persist_admission
from api.streaming.table_stream.row_run_admission import PersistAdmission


@dataclass(frozen=True, slots=True)
class PersistDecision:
    """Outcome of :func:`decide_scores_row_persist`.

    The only production persist gate for scores row writes. Registry
    :class:`~api.streaming.table_stream.row_run_admission.PersistAdmission` is
    mapped here under lock -- callers must not branch on admission directly.

    ``allowed`` -- write may proceed (retained shell admission).
    ``should_retire`` -- only meaningful on refuse: retire compact cancel
    admission memory after the silent no-write. Unknown / absent refuse does
    not retire.
    """

    allowed: bool
    should_retire: bool = False

    @classmethod
    def allow(cls) -> PersistDecision:
        return cls(allowed=True, should_retire=False)

    @classmethod
    def refuse(cls, *, should_retire: bool) -> PersistDecision:
        return cls(allowed=False, should_retire=should_retire)


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Decide whether a scores ``rowComplete`` persist may write.

    Sole production persist gate. Maps registry-internal
    :class:`~api.streaming.table_stream.row_run_admission.PersistAdmission`:

    - ``ALLOW`` -- ``PersistAdmission.ALLOW`` (``REGISTERED`` or ``DETACHED`` shell)
    - ``REFUSE(should_retire=True)`` -- ``PersistAdmission.CANCEL_DENY``
    - ``REFUSE(should_retire=False)`` -- ``PersistAdmission.ABSENT``

    Both refuse outcomes must not write. Persist policy treats them as silent
    no-ops (never raise): cancelled late workers and unknown ids share the same
    "no durable write" contract. The only behavioral difference is whether
    compact cancel admission should be retired.

    Cancel intent must go through
    :func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`
    (``RowLifecycleOp.CANCEL``) / registry ``mark_row_run_cancelled``;
    the live cancel token is not a persist gate. Shell ``RowRunPhase`` is not
    consulted here -- only :func:`get_persist_admission` (registry-internal).
    """
    admission = get_persist_admission(run_id)
    if admission is PersistAdmission.ALLOW:
        return PersistDecision.allow()
    if admission is PersistAdmission.CANCEL_DENY:
        return PersistDecision.refuse(should_retire=True)
    return PersistDecision.refuse(should_retire=False)
