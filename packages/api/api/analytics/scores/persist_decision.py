"""Single production gate for scores durable persist admission and retire plan."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.scores.tier_row_run_registry import (
    get_persist_admission,
    get_row_run_phase,
)
from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase


@dataclass(frozen=True, slots=True)
class PersistDecision:
    """Outcome of :func:`decide_scores_row_persist`.

    The only production persist gate for scores row writes. Registry
    :class:`~api.streaming.table_stream.row_run_admission.PersistAdmission` is
    mapped here under lock -- callers must not branch on admission or shell
    phase directly.

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


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Decide whether a scores ``rowComplete`` persist may write, and retire plan.

    Sole production persist gate. Maps registry-internal
    :class:`~api.streaming.table_stream.row_run_admission.PersistAdmission`
    and retained-shell phase into one decision:

    - ``ALLOW(retire_after_write=False)`` -- ``REGISTERED`` shell
    - ``ALLOW(retire_after_write=True)`` -- ``DETACHED`` shell (late persist)
    - ``REFUSE(should_retire=True)`` -- ``PersistAdmission.CANCEL_DENY``
    - ``REFUSE(should_retire=False)`` -- ``PersistAdmission.ABSENT``

    Both refuse outcomes must not write. Persist policy treats them as silent
    no-ops (never raise): cancelled late workers and unknown ids share the same
    "no durable write" contract. The only behavioral difference is whether
    compact cancel admission should be retired.

    Cancel intent must go through
    :func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`
    (``RowLifecycleOp.CANCEL``) / registry ``mark_row_run_cancelled``;
    the live cancel token is not a persist gate. Callers must not re-read
    shell phase beside this decision -- ``retire_after_write`` owns post-write
    retire.
    """
    admission = get_persist_admission(run_id)
    if admission is PersistAdmission.ALLOW:
        phase = get_row_run_phase(run_id)
        return PersistDecision.allow(
            retire_after_write=phase is RowRunPhase.DETACHED,
        )
    if admission is PersistAdmission.CANCEL_DENY:
        return PersistDecision.refuse(should_retire=True)
    return PersistDecision.refuse(should_retire=False)
