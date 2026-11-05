"""Fleet job-wire fields for the submission open.

The shared open-turn and catch-up rules live in ``api.analytics.off_mode``.
This module writes those fields from a submission open the caller already
resolved. It does not read the stored backfill record.
"""

from __future__ import annotations

from typing import Any

from api.analytics.off_mode import (
    BACKFILL_EARLIER_TURNS_WIRE_FIELD,
    apply_off_mode_job_wire_fields,
)
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen


def stamp_submission_open(
    wire: dict[str, Any],
    scope: ComputeScope,
    submission_open: SubmissionOpen | None,
) -> None:
    """Write one submission open onto a fleet job wire.

    The carried open is copied as resolved. ``openTurn`` and ``catchUp`` are
    present only when backfill is off and the open turn is set. No submission
    open clears those two fields and does not write ``backfillEarlierTurns``.
    """
    if isinstance(scope.turn, bool) or not isinstance(scope.turn, int):
        raise ValueError("fleet job wire requires concrete turn")
    open_turn = None if submission_open is None else submission_open.open_turn
    backfill_enabled = False if submission_open is None else submission_open.backfill_earlier_turns
    apply_off_mode_job_wire_fields(
        wire,
        open_turn=open_turn,
        turn=scope.turn,
        backfill_enabled=backfill_enabled,
    )
    if submission_open is not None:
        wire[BACKFILL_EARLIER_TURNS_WIRE_FIELD] = backfill_enabled
