"""One cancel command for scores row runs: admission + delivery + token.

Cancel (not detach) must apply all three sides of cancel intent together so
persist denial, stream silence, and in-flight solve abort cannot drift.
"""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.scores.tier_row_run_registry import mark_row_run_cancelled
from api.streaming.table_stream import stream_drain


def apply_scores_row_cancel(
    run_id: str,
    *,
    cancel_token: Callable[[], None] | None = None,
) -> None:
    """Apply durable cancel admission, seal stream cancel, then cancel the token.

    Order:
    1. Compact cancel admission (drops any RowRun shell; remembers run_id).
    2. Seal stream cancel (``CANCELED`` + drain closed) via
       :func:`stream_drain.seal_canceled` (idempotent with multiplex seal).
    3. Session cancel token (stop in-flight tier work), when provided.

    Detach must never call this: detached workers may still finish and persist.
    """
    dropped = mark_row_run_cancelled(run_id)
    stream_drain.seal_canceled(run_id)
    if cancel_token is not None:
        cancel_token()
    elif dropped is not None:
        dropped.session.cancel_token.cancel()
