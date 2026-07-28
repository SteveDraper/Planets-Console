"""Pluggable stop-gate for budgeted layout-prior solvers."""

from __future__ import annotations

from typing import Protocol


class StopGate(Protocol):
    """Polled by discrete solvers to decide whether to stop searching."""

    def should_stop(self) -> bool:
        """Return True when the solver should halt and keep the incumbent."""


class NeverStopGate:
    """Stop-gate that never fires (used by the exhaustive enumerator)."""

    def should_stop(self) -> bool:
        return False
