"""Fleet job-wire fields for the submission open.

``stamp_submission_open`` is the one writer of ``openTurn``, ``catchUp``, and
``backfillEarlierTurns`` on a fleet job wire. It copies a submission open the
caller already resolved. It does not read the stored backfill record.
``parse_off_mode_wire`` checks those fields when a job is read back.
"""

from __future__ import annotations

from typing import Any

from api.analytics.off_mode import (
    BACKFILL_EARLIER_TURNS_WIRE_FIELD,
    CATCH_UP_WIRE_FIELD,
    OPEN_TURN_WIRE_FIELD,
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
    present only when backfill is off and the open turn is set. ``catchUp`` is
    true for an earlier hop of that open and false on the open turn itself.
    No submission open clears those two fields and does not write
    ``backfillEarlierTurns``.
    """
    turn = scope.turn
    if isinstance(turn, bool) or not isinstance(turn, int):
        raise ValueError("fleet job wire requires concrete turn")
    wire.pop(OPEN_TURN_WIRE_FIELD, None)
    wire.pop(CATCH_UP_WIRE_FIELD, None)
    if submission_open is None:
        return
    wire[BACKFILL_EARLIER_TURNS_WIRE_FIELD] = submission_open.backfill_earlier_turns
    open_turn = submission_open.open_turn
    if open_turn is None or submission_open.backfill_earlier_turns:
        return
    wire[OPEN_TURN_WIRE_FIELD] = open_turn
    wire[CATCH_UP_WIRE_FIELD] = turn < open_turn
