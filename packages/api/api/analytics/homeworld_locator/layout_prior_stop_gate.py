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
        self._start = time.perf_counter()
        self._deadline = self._start + (budget_ms / 1000.0)

    def should_stop(self) -> bool:
        return time.perf_counter() >= self._deadline

    def has_fired(self) -> bool:
        return time.perf_counter() >= self._deadline

    def budget_progress(self) -> float:
        """Fraction of wall-clock budget consumed in ``[0, 1]``."""
        if self.budget_ms <= 0:
            return 1.0
        elapsed = time.perf_counter() - self._start
        return min(1.0, max(0.0, elapsed / (self.budget_ms / 1000.0)))


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

    def budget_progress(self) -> float:
        """Fraction of step budget consumed before the current step in ``[0, 1]``.

        After ``should_stop`` returns False for the k-th allowed step,
        ``_steps_started == k`` and progress is ``(k - 1) / max_steps`` so the
        first step starts at progress 0.
        """
        if self.max_steps <= 0:
            return 1.0
        completed = max(0, self._steps_started - 1)
        return min(1.0, completed / self.max_steps)


def stop_gate_budget_progress(stop_gate: StopGate) -> float:
    """Budget fraction in ``[0, 1]`` for temperature schedules; 0 if unknown."""
    if isinstance(stop_gate, DeadlineStopGate):
        return stop_gate.budget_progress()
    if isinstance(stop_gate, MaxStepsStopGate):
        return stop_gate.budget_progress()
    return 0.0


def stop_gate_info(stop_gate: StopGate) -> LayoutPriorStopGateInfo:
    """Describe a stop-gate for solver run telemetry."""
    if isinstance(stop_gate, DeadlineStopGate):
        return LayoutPriorStopGateInfo(kind="deadline", budget_ms=stop_gate.budget_ms)
    if isinstance(stop_gate, MaxStepsStopGate):
        return LayoutPriorStopGateInfo(kind="max_steps", max_steps=stop_gate.max_steps)
    return LayoutPriorStopGateInfo(kind="never")
