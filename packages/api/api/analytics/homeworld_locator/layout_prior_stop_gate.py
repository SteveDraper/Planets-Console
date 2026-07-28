"""Pluggable stop-gate for budgeted layout-prior solvers."""

from __future__ import annotations

import time
from typing import Protocol

from api.analytics.homeworld_locator.layout_prior_report import LayoutPriorStopGateInfo
from api.errors import ValidationError


class StopGate(Protocol):
    """Polled by discrete solvers to decide whether to stop searching."""

    def should_stop(self) -> bool:
        """Return True when the solver should halt and keep the incumbent."""


class NeverStopGate:
    """Stop-gate that never fires (used by the exhaustive enumerator)."""

    def should_stop(self) -> bool:
        return False

    def has_fired(self) -> bool:
        return False


class DeadlineStopGate:
    """Wall-clock stop-gate for production anneal (monotonic clock)."""

    def __init__(self, budget_ms: int) -> None:
        if budget_ms < 0:
            raise ValidationError(f"budget_ms must be >= 0, got {budget_ms}")
        self.budget_ms = budget_ms
        self._deadline = time.perf_counter() + (budget_ms / 1000.0)

    def should_stop(self) -> bool:
        return time.perf_counter() >= self._deadline

    def has_fired(self) -> bool:
        return time.perf_counter() >= self._deadline


class MaxStepsStopGate:
    """Step-count stop-gate for deterministic tests.

    Polled once per discrete SA step *before* the step runs. ``MaxSteps(0)``
    stops immediately (greedy init only); ``MaxSteps(n)`` allows ``n`` steps.
    """

    def __init__(self, max_steps: int) -> None:
        if max_steps < 0:
            raise ValidationError(f"max_steps must be >= 0, got {max_steps}")
        self.max_steps = max_steps
        self._steps_started = 0

    def should_stop(self) -> bool:
        if self._steps_started >= self.max_steps:
            return True
        self._steps_started += 1
        return False

    def has_fired(self) -> bool:
        return self._steps_started >= self.max_steps


def stop_gate_info(stop_gate: StopGate) -> LayoutPriorStopGateInfo:
    """Describe a stop-gate for solver run telemetry."""
    if isinstance(stop_gate, DeadlineStopGate):
        return LayoutPriorStopGateInfo(kind="deadline", budget_ms=stop_gate.budget_ms)
    if isinstance(stop_gate, MaxStepsStopGate):
        return LayoutPriorStopGateInfo(kind="max_steps", max_steps=stop_gate.max_steps)
    return LayoutPriorStopGateInfo(kind="never")
