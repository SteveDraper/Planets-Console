"""Sole writer API for table-stream drain closed state.

Drain-closed lives only on ``RowStreamResolution.multiplex_closed`` in the
process-wide resolution registry. UUID run ids are never reused, so closed bits
remain as routing history; soft reopen clears the bit only while still
``SOFT_PROVISIONAL``.

Cancel silence is one operation -- :func:`seal_canceled` (FSM ``CANCELED`` +
drain closed). Exactly two justified callers:

- ``multiplex`` -- generic token-observed seal when any analytic's session
  cancel token is seen in the drain loop (covers fleet and analytics without
  a cancel-intent path).
- ``apply_scores_row_cancel`` -- scores-specific immediate seal when cancel is
  applied, before multiplex necessarily notices the token.

A second call is a no-op (idempotent). No other module may seal cancel finish.
"""

from __future__ import annotations

from api.streaming.table_stream.row_stream_resolution import RowStreamDelivery
from api.streaming.table_stream.row_stream_resolution_registry import (
    clear_multiplex_closed_if_soft,
    is_multiplex_closed,
    mark_multiplex_closed,
    seal_canceled_finish,
)


def close(run_id: str) -> None:
    """Mark ``run_id`` drain-closed for multiplex and terminal routing."""
    mark_multiplex_closed(run_id)


def seal_canceled(run_id: str) -> RowStreamDelivery:
    """Sole cancel-silence operation: ``CANCELED`` + drain closed (idempotent).

    Call only from multiplex (token-observed) or scores cancel intent (immediate).
    """
    return seal_canceled_finish(run_id)


def reopen_if_soft(run_id: str) -> bool:
    """Re-open drain only while resolution is still soft-provisional.

    Returns True when drain was reopened (caller should wake multiplex).
    """
    return clear_multiplex_closed_if_soft(run_id)


def is_closed(run_id: str) -> bool:
    """True when drain is closed for ``run_id``."""
    return is_multiplex_closed(run_id)
