"""Explicit submission opens and execution probes for direct job-wire builder calls."""

from __future__ import annotations

from api.compute.submission_open import SubmissionOpen


def explicit_submission_open(
    *,
    open_turn: int | None = None,
    backfill_earlier_turns: bool = False,
) -> SubmissionOpen:
    """Open a direct builder call carries.

    Backfill is off and no root is named unless the test sets them.
    """
    return SubmissionOpen(
        open_turn=open_turn,
        backfill_earlier_turns=backfill_earlier_turns,
    )


def live_execution() -> bool:
    """The ``is_execution_live`` probe a direct builder call carries: always live."""
    return True
