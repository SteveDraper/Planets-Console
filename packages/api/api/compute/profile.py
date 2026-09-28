"""Declarative compute execution profiles per analytic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ComputeBackend = Literal["inline", "thread", "interpreter", "process"]

VALID_COMPUTE_BACKENDS: frozenset[str] = frozenset({"inline", "thread", "interpreter", "process"})


@dataclass(frozen=True)
class ComputeStepSpec:
    """One schedulable step inside a compute node."""

    step_kind: str
    backend: ComputeBackend


@dataclass(frozen=True)
class AnalyticComputeProfile:
    """Declared step kinds and worker backends for one analytic."""

    steps: tuple[ComputeStepSpec, ...]
    # When False, table/map REST (`get_turn_analytics`) does not ensure through
    # the orchestrator. Scores uses this: the REST table is a TurnInfo projection
    # and inference lives on the table stream, not batch compute.
    route_table_map: bool = True
