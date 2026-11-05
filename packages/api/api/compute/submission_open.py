"""Submission root turn and backfill choice for one compute submission.

Generic compute-plane value. Analytics read its fields. This module does not
import analytic code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubmissionOpen:
    """Root turn and backfill choice carried by one submission.

    ``open_turn`` is None when the submission has not named a root and the
    scope turn is not a concrete int. A carried ``open_turn`` wins over the
    request scope's turn. ``backfill_earlier_turns`` is the choice for this
    submission once entry has resolved it, or the choice a hop was planned with.
    """

    open_turn: int | None = None
    backfill_earlier_turns: bool = False
