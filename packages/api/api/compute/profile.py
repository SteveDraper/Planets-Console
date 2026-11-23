"""Declarative compute execution profiles per analytic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

# Backends whose steps run on an executor outside the pool worker thread.
RemoteComputeBackend = Literal["interpreter", "process"]
ComputeBackend = Literal["inline", "thread", RemoteComputeBackend]
# Backends whose steps run as compute worker pool items.
PoolComputeBackend = Literal["thread", RemoteComputeBackend]

REMOTE_COMPUTE_BACKENDS: tuple[RemoteComputeBackend, ...] = get_args(RemoteComputeBackend)
VALID_COMPUTE_BACKENDS: frozenset[ComputeBackend] = frozenset(get_args(ComputeBackend))

# Where a step runs: on the submitting thread, or as a pool item.
StepSurface = Literal["inline", "pool"]


@dataclass(frozen=True)
class ComputeStepSpec:
    """One schedulable step inside a compute node."""

    step_kind: str
    backend: ComputeBackend

    @property
    def surface(self) -> StepSurface:
        """``inline`` for the inline backend; every other backend runs as a pool item."""
        return "inline" if self.backend == "inline" else "pool"


@dataclass(frozen=True)
class AnalyticComputeProfile:
    """Declared step kinds and worker backends for one analytic."""

    steps: tuple[ComputeStepSpec, ...]
    # When False, table/map REST (`get_turn_analytics`) does not ensure through
    # the orchestrator. Scores uses this: the REST table is a TurnInfo projection
    # and inference lives on the table stream, not batch compute.
    route_table_map: bool = True

    @property
    def step_kinds(self) -> tuple[str, ...]:
        """The declared step kinds, in profile order."""
        return tuple(step.step_kind for step in self.steps)

    def has_step_kind(self, step_kind: str) -> bool:
        """Whether ``step_kind`` names a step of this profile."""
        return step_kind in self.step_kinds
