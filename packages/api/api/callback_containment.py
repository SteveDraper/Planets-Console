"""Contain a callback's failure: log it with its label and keep going.

A contained callback is one whose caller must not fail because it failed:
an observer the orchestrator notifies, or one step of a fan-out that runs
every step before raising. Only ``Exception`` is contained, so an interrupt
(``KeyboardInterrupt``, ``SystemExit``, any other ``BaseException``) still
propagates and skips whatever would have run after it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

logger = logging.getLogger(__name__)

# Names the kind of contained callback in a failure log.
ContainmentLabel = Literal[
    "Post-lock callback",
    "Ready-queue listener",
    "Inline-start listener",
    "Fleet ledger bump",
    "Backfill earlier turns listener",
]


def run_contained(callback: Callable[[], None], label: ContainmentLabel) -> Exception | None:
    """Run ``callback``; log and return its ``Exception``, or return None when it succeeds."""
    try:
        callback()
    except Exception as error:
        logger.exception("%s %r failed", label, callback)
        return error
    return None


class FailureCollector:
    """Run callbacks contained and keep the first failure for the caller to raise.

    Every failure is logged where it is contained. The caller decides how to
    raise ``first_error`` (raw, or chained to its own typed error), so the
    first failure is logged again by whoever handles that raise.
    """

    def __init__(self) -> None:
        self._first_error: Exception | None = None

    @property
    def first_error(self) -> Exception | None:
        """The first failure ``run`` contained, or None when every callback succeeded."""
        return self._first_error

    def run(self, callback: Callable[[], None], label: ContainmentLabel) -> None:
        """Run ``callback`` contained; keep its failure when it is the first."""
        error = run_contained(callback, label)
        if self._first_error is None:
            self._first_error = error
