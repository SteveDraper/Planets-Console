"""Replaceable layout-prior solver protocol, solution type, and factory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from api.analytics.homeworld_locator.layout_prior_problem import LayoutPriorProblem
from api.analytics.homeworld_locator.layout_prior_stop_gate import (
    DeadlineStopGate,
    NeverStopGate,
    StopGate,
)
from api.errors import ValidationError

LAYOUT_PRIOR_SOLVER_ENUMERATE = "enumerate"
LAYOUT_PRIOR_SOLVER_ANNEAL = "anneal"

_KNOWN_LAYOUT_PRIOR_SOLVERS = frozenset({LAYOUT_PRIOR_SOLVER_ENUMERATE, LAYOUT_PRIOR_SOLVER_ANNEAL})


@dataclass(frozen=True)
class LayoutPriorSolution:
    """Result of a layout-prior solve for one problem instance.

    ``chosen_planet_ids_by_sector`` maps choice-sector index to selected planet id.
    ``stand_in_positions_by_sector`` holds stand-in coordinates used for scoring
    (fixed mid for the enumerator; refined samples after anneal).
    """

    chosen_planet_ids_by_sector: Mapping[int, int]
    stand_in_positions_by_sector: Mapping[int, tuple[float, float]]
    cost: float
    tie_key: tuple[tuple[int, int], ...]


class LayoutPriorSolver(Protocol):
    """Pure solver: sector participation + stop-gate -> discrete selection."""

    def solve(
        self,
        problem: LayoutPriorProblem,
        *,
        stop_gate: StopGate,
    ) -> LayoutPriorSolution:
        """Return the best incumbent selection found under ``stop_gate``."""


def layout_prior_solver_from_name(name: str) -> LayoutPriorSolver:
    """Construct a named layout-prior solver implementation."""
    if name == LAYOUT_PRIOR_SOLVER_ENUMERATE:
        from api.analytics.homeworld_locator.layout_prior_enumerate import (
            EnumeratingLayoutPriorSolver,
        )

        return EnumeratingLayoutPriorSolver()
    if name == LAYOUT_PRIOR_SOLVER_ANNEAL:
        from api.analytics.homeworld_locator.layout_prior_anneal import (
            AnnealingLayoutPriorSolver,
        )

        return AnnealingLayoutPriorSolver()
    known = ", ".join(sorted(_KNOWN_LAYOUT_PRIOR_SOLVERS))
    raise ValidationError(f"Unknown layout_prior_solver {name!r}; expected one of: {known}")


def layout_prior_solver_from_config() -> LayoutPriorSolver:
    """Resolve the configured layout-prior solver (defaults to anneal)."""
    from api.config import get_config

    return layout_prior_solver_from_name(get_config().homeworld_locator.layout_prior_solver)


def layout_prior_stop_gate_from_config() -> StopGate:
    """Production stop-gate for the configured solver.

    Anneal uses ``DeadlineStopGate(layout_prior_budget_ms)``. Enumerate ignores
    the gate and receives ``NeverStopGate``.
    """
    from api.config import get_config

    cfg = get_config().homeworld_locator
    if cfg.layout_prior_solver == LAYOUT_PRIOR_SOLVER_ANNEAL:
        return DeadlineStopGate(cfg.layout_prior_budget_ms)
    return NeverStopGate()
