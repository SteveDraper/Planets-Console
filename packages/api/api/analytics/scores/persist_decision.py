"""Scores durable persist plan type and pure admission→decision map.

The sole production gate that *reads registry state* is
:func:`api.analytics.scores.tier_row_run_registry.decide_scores_row_persist`
(atomic under one lock). This module owns the decision type and the pure map
from snapshotted admission + shell phase -- no registry import, no facade hop.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase


@dataclass(frozen=True, slots=True)
class PersistDecision:
    """Outcome of :func:`~api.analytics.scores.tier_row_run_registry.decide_scores_row_persist`.

    The only production persist plan for scores row writes. Registry
    :class:`~api.streaming.table_stream.row_run_admission.PersistAdmission`
    and retained-shell phase are snapshotted atomically into this decision
    (one registry lock hold) -- callers must not branch on admission or shell
    phase directly.

    Once this decision is taken, a later cancel does not revoke it: the persist
    policy may write (or refuse) according to these flags without re-probing
    admission. Cancel that lands before the snapshot is already reflected here.

    ``allowed`` -- write may proceed (retained shell admission).
    ``should_retire`` -- only meaningful on refuse: retire compact cancel
    admission memory after the silent no-write. Unknown / absent refuse does
    not retire.
    ``retire_after_write`` -- only meaningful on allow: retire the retained
    shell after a successful durable write (``DETACHED`` late persist). Live
    ``REGISTERED`` shells stay until stream finalize retires them.
    """

    allowed: bool
    should_retire: bool = False
    retire_after_write: bool = False

    @classmethod
    def allow(cls, *, retire_after_write: bool = False) -> PersistDecision:
        return cls(
            allowed=True,
            should_retire=False,
            retire_after_write=retire_after_write,
        )

    @classmethod
    def refuse(cls, *, should_retire: bool) -> PersistDecision:
        return cls(
            allowed=False,
            should_retire=should_retire,
            retire_after_write=False,
        )


def persist_decision_from_admission(
    admission: PersistAdmission,
    *,
    phase: RowRunPhase | None,
) -> PersistDecision:
    """Pure map from snapshotted admission + shell phase to a persist plan.

    Call only with values read under the same registry lock hold as the
    production gate. Shell must accompany ``ALLOW``; a missing shell is treated
    as absent refuse.
    """
    if admission is PersistAdmission.ALLOW:
        if phase is None:
            return PersistDecision.refuse(should_retire=False)
        return PersistDecision.allow(
            retire_after_write=phase is RowRunPhase.DETACHED,
        )
    if admission is PersistAdmission.CANCEL_DENY:
        return PersistDecision.refuse(should_retire=True)
    return PersistDecision.refuse(should_retire=False)
