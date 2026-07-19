"""Scores applicator for the three table-stream row-run lifecycle ops.

Generic vocabulary lives in
:mod:`api.streaming.table_stream.row_run_admission` (``RowLifecycleOp``).
This module is the **scores** owner that applies the ownership-matrix sides
(shell + admission + drain/token) for ``DETACH`` / ``CANCEL`` / ``RETIRE``.

Scheduler abort_scope and stream-map pops stay on the scheduler plane -- they
are not part of this command. Fleet does not use this module yet.

Cancel silence uses the sole cancel-seal operation
:func:`stream_drain.seal_canceled`. This module is the scores-specific
*immediate* seal caller (silence as soon as cancel is applied). Multiplex is
the generic *token-observed* caller for any analytic; a later multiplex seal
is a no-op.
"""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.scores.tier_row_run_registry import (
    detach_row_run,
    mark_row_run_cancelled,
    retire_row_run,
)
from api.streaming.table_stream import stream_drain
from api.streaming.table_stream.row_run_admission import RowLifecycleOp


def apply_scores_row_lifecycle(
    op: RowLifecycleOp,
    run_id: str,
    *,
    cancel_token: Callable[[], None] | None = None,
) -> None:
    """Apply one scores row-run lifecycle op per the ownership matrix.

    ``DETACH`` -- ``REGISTERED`` → ``DETACHED``; keep ``ALLOW``; no seal / token.
    ``CANCEL`` -- drop shell + ``CANCEL_DENY`` + :func:`stream_drain.seal_canceled`
    + session cancel token (``cancel_token`` override or shell's token).
    ``RETIRE`` -- drop shell and clear admission; leave stream resolution.

    Detach must never be routed as cancel: detached workers may still finish
    and persist. Abort of orchestrator scope remains the scheduler's
    ``cancel_run`` (outside the scheduler lock).
    """
    match op:
        case RowLifecycleOp.DETACH:
            detach_row_run(run_id)
        case RowLifecycleOp.RETIRE:
            retire_row_run(run_id)
        case RowLifecycleOp.CANCEL:
            dropped = mark_row_run_cancelled(run_id)
            stream_drain.seal_canceled(run_id)
            if cancel_token is not None:
                cancel_token()
            elif dropped is not None:
                dropped.session.cancel_token.cancel()


def apply_scores_row_cancel(
    run_id: str,
    *,
    cancel_token: Callable[[], None] | None = None,
) -> None:
    """Convenience: :func:`apply_scores_row_lifecycle` for ``RowLifecycleOp.CANCEL``."""
    apply_scores_row_lifecycle(
        RowLifecycleOp.CANCEL,
        run_id,
        cancel_token=cancel_token,
    )
