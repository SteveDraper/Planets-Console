"""Submission root turn and backfill choice for one compute submission.

Generic compute-plane value. Analytics read its fields. This module does not
import analytic code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from api.compute.scope import ComputeScope


@dataclass(frozen=True)
class SubmissionOpen:
    """Root turn and backfill choice carried by one submission.

    ``open_turn`` is None when the submission has not named a root and the
    scope turn is not a concrete int. A carried ``open_turn`` wins over the
    request scope's turn. ``backfill_earlier_turns`` is the choice for this
    submission once entry has resolved it, or the choice a hop was planned with.
    ``on_walk`` is set by the root analytic's plan hook when this submission
    is an on-walk. Nodes the walk plans and hops resubmitted from them keep it.
    """

    open_turn: int | None = None
    backfill_earlier_turns: bool = False
    on_walk: bool = False


class SubmissionOpenReader(Protocol):
    """Reads the submission open of one in-memory compute node."""

    def submission_open_for(self, scope: ComputeScope) -> SubmissionOpen | None:
        """Submission open of one node, or None when that scope is not in memory."""
        ...
