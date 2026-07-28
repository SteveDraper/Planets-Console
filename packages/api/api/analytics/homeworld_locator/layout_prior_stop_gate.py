"""Pluggable stop-gate for budgeted layout-prior solvers."""

from __future__ import annotations

import time
from typing import Protocol


class StopGate(Protocol):
    """Polled by discrete solvers to decide whether to stop searching."""

    def should_stop(self) -> bool:
        """Return True when the solver should halt and keep the incumbent."""


class NeverStopGate:
    """Stop-gate that never fires (used by the exhaustive enumerator)."""

    def should_stop(self) -> bool:
        return False


class DeadlineStopGate:
    """Wall-clock stop-gate for production anneal (monotonic clock)."""

    def __init__(self, budget_ms: int) -> None:
        if budget_ms < 0:
            raise ValueError(f"budget_ms must be >= 0, got {budget_ms}")
        self._deadline = time.perf_counter() + (budget_ms / 1000.0)

    def should_stop(self) -> bool:
        return time.perf_counter() >= self._deadline


class MaxStepsStopGate:
    """Step-count stop-gate for deterministic tests.

    Polled once per discrete SA step *before* the step runs. ``MaxSteps(0)``
    stops immediately (greedy init only); ``MaxSteps(n)`` allows ``n`` steps.
    """

    def __init__(self, max_steps: int) -> None:
        if max_steps < 0:
            raise ValueError(f"max_steps must be >= 0, got {max_steps}")
        self._max_steps = max_steps
        self._steps_started = 0

    def should_stop(self) -> bool:
        if self._steps_started >= self._max_steps:
            return True
        self._steps_started += 1
        return False
