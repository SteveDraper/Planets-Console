"""Generic table-stream row-run shell phase and persist admission.

Any table-stream analytic that retains per-row shells across stream detach
(detach ≠ cancel) can reuse these types. They are **not** scores-specific and
are **not** compute-orchestrator multi-step DAG types -- those stay under
``api.compute``.

Shell phase vs persist admission
--------------------------------
``RowRunPhase`` describes a *retained* shell only (``REGISTERED`` / ``DETACHED``).
Cancel never becomes a shell phase: the shell is dropped and compact
cancelled-admission memory is recorded separately.

``PersistAdmission`` is the registry-internal vocabulary for that admission
memory (shell present → ``ALLOW``; compact cancel → ``CANCEL_DENY``; else
``ABSENT``). Production persist writers must not branch on it directly -- use
the analytic's ``PersistDecision`` / ``decide_*`` gate (scores:
:func:`api.analytics.scores.persist_decision.decide_scores_row_persist`).

``RowLifecycleOp`` names the three generic ops (``DETACH`` / ``CANCEL`` /
``RETIRE``). Scores applies them via
:func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`.
"""

from __future__ import annotations

from enum import StrEnum


class RowRunPhase(StrEnum):
    """Lifecycle of a *retained* row-run shell (not persist-admission memory).

    ``REGISTERED`` -- live shell indexed by scope.
    ``DETACHED`` -- stream dropped; shell retained by ``run_id`` for late persist.
    Cancel intent does not become a shell phase: the shell is dropped and compact
    cancelled-admission memory is recorded separately (see ``PersistAdmission``).
    """

    REGISTERED = "registered"
    DETACHED = "detached"


class PersistAdmission(StrEnum):
    """Registry-internal persist-write admission for a ``run_id``.

    Independent of shell phase. Production callers use ``PersistDecision``
    (mapped from this enum under lock); do not treat this as a second public gate.

    ``ALLOW`` -- retained ``REGISTERED`` or ``DETACHED`` shell.
    ``CANCEL_DENY`` -- compact cancelled-admission memory (no shell).
    ``ABSENT`` -- never-seen / retired / superseded cancel.
    """

    ALLOW = "allow"
    CANCEL_DENY = "cancel_deny"
    ABSENT = "absent"


class RowLifecycleOp(StrEnum):
    """Generic table-stream row-run lifecycle ops (detach ≠ cancel ≠ retire).

    Vocabulary only -- each analytic that retains shells across stream detach
    applies these via its own lifecycle command (scores:
    :func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`).
    Scheduler abort / stream-map pops stay on the scheduler plane.

    ``DETACH`` -- ``REGISTERED`` → ``DETACHED``; admission stays ``ALLOW``;
    no seal, no token cancel, no abort.
    ``CANCEL`` -- drop shell; compact ``CANCEL_DENY``; seal cancel; cancel token
    (abort is scheduler-owned, outside this op).
    ``RETIRE`` -- drop shell and clear admission; leave stream resolution.
    """

    DETACH = "detach"
    CANCEL = "cancel"
    RETIRE = "retire"
