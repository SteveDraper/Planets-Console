"""Single production gate for scores durable persist admission and retire plan."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PersistDecision:
    """Outcome of :func:`decide_scores_row_persist`.

    The only production persist gate for scores row writes. Registry
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


def decide_scores_row_persist(run_id: str) -> PersistDecision:
    """Decide whether a scores ``rowComplete`` persist may write, and retire plan.

    Sole production persist gate. Delegates to
    :func:`~api.analytics.scores.tier_row_run_registry.snapshot_persist_decision`
    so admission and shell phase are read under one registry lock:

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
    retire. After this returns, a subsequent cancel race does not matter; the
    decision stands for that persist attempt.
    """
    from api.analytics.scores.tier_row_run_registry import snapshot_persist_decision

    return snapshot_persist_decision(run_id)
