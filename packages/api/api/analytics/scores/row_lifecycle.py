"""Scores applicator for the three table-stream row-run lifecycle ops.

Generic vocabulary lives in
:mod:`api.streaming.table_stream.row_run_admission` (``RowLifecycleOp``).
This module is the **scores** owner that applies the ownership-matrix sides
(shell + admission + drain/token) for ``DETACH`` / ``CANCEL`` / ``RETIRE``.

``CANCEL`` takes either a run id or a :class:`StampedLadderRun`: the run a
scope's tier-ladder stamp names for one scores node execution. The stamped
target is how an aborted scores execution stops its solve; the registry
resolves the stamp and drops that shell in one hold, so a newer execution's
claim cannot lose its run in between.

Scheduler abort_scope and stream-map pops stay on the scheduler plane -- they
are not part of this command. Fleet does not use this module (token-only
cancel; ADR 0006).

Cancel silence uses the sole cancel-seal operation
:func:`stream_drain.seal_canceled`. This module is the scores-specific
*immediate* seal caller (silence as soon as cancel is applied). Multiplex is
the generic *token-observed* caller for any analytic; a later multiplex seal
is a no-op.
"""

from __future__ import annotations

from api.analytics.scores.tier_row_run_registry import (
    StampedLadderRun,
    _detach_row_run,
    _mark_row_run_cancelled,
    _mark_stamped_row_run_cancelled,
    _retire_row_run,
)
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_run_admission import RowLifecycleOp


def apply_scores_row_lifecycle(
    op: RowLifecycleOp,
    target: str | StampedLadderRun,
) -> str | None:
    """Apply one scores row-run lifecycle op per the ownership matrix.

    Sole production mutation entry for shell + admission + cancel seal + token.
    Do not call registry ``_detach_row_run`` / ``_mark_row_run_cancelled`` /
    ``_mark_stamped_row_run_cancelled`` / ``_retire_row_run`` from adapters --
    go through this command.

    ``DETACH`` (run id) -- ``REGISTERED`` → ``DETACHED`` and keep ``ALLOW`` while the
    scope's ladder stamp names the run; otherwise the RETIRE side. No seal / token.
    ``CANCEL`` -- drop shell + ``CANCEL_DENY`` + :func:`stream_drain.seal_canceled`
    + the shell's session cancel token. A run id names the run directly; a
    :class:`StampedLadderRun` names the run the scope's ladder stamp holds for
    that execution, and also releases the stamp.
    ``RETIRE`` (run id) -- drop shell and clear admission; leave stream resolution.

    Returns the id of the run whose shell ``CANCEL`` dropped, so the
    scheduler can forget it; otherwise None.

    Detach must never be routed as cancel: detached workers may still finish
    and persist. Abort of orchestrator scope remains the scheduler's
    ``cancel_run`` (outside the scheduler lock).
    """
    if op is RowLifecycleOp.CANCEL:
        return _cancel(target)
    if not isinstance(target, str):
        raise TypeError(f"{op} takes a run id, not {target!r}")
    match op:
        case RowLifecycleOp.DETACH:
            _detach_row_run(target)
        case RowLifecycleOp.RETIRE:
            _retire_row_run(target)
    return None


def _cancel(target: str | StampedLadderRun) -> str | None:
    match target:
        case StampedLadderRun():
            dropped = _mark_stamped_row_run_cancelled(target)
            if dropped is None:
                return None
            run_id = dropped.run_id
        case str():
            dropped = _mark_row_run_cancelled(target)
            run_id = target
    stream_drain.seal_canceled(run_id)
    if dropped is None:
        return None
    dropped.session.cancel_token.cancel()
    return run_id
