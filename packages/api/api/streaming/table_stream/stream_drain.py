"""Sole writer API for table-stream drain closed state.

Drain-closed lives only on ``RowStreamResolution.multiplex_closed`` in the
process-wide resolution registry. UUID run ids are never reused, so closed bits
remain as routing history; soft reopen clears the bit only while still
``SOFT_PROVISIONAL``.
"""

from __future__ import annotations

from api.streaming.table_stream.row_stream_resolution_registry import (
    clear_multiplex_closed_if_soft,
    is_multiplex_closed,
    mark_multiplex_closed,
)


def close(run_id: str) -> None:
    """Mark ``run_id`` drain-closed for multiplex and terminal routing."""
    mark_multiplex_closed(run_id)


def reopen_if_soft(run_id: str) -> bool:
    """Re-open drain only while resolution is still soft-provisional.

    Returns True when drain was reopened (caller should wake multiplex).
    """
    return clear_multiplex_closed_if_soft(run_id)


def is_closed(run_id: str) -> bool:
    """True when drain is closed for ``run_id``."""
    return is_multiplex_closed(run_id)
