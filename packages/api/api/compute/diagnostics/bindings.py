"""Orchestrator bindings registered with the compute diagnostics observer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.compute.orchestrator import ComputeOrchestrator


@dataclass(frozen=True)
class BoundOrchestrator:
    """One orchestrator registered with the diagnostics observer."""

    orchestrator: ComputeOrchestrator
    game_id: int
    perspective: int
    ambient_turn: int
    unregister_dispatch_gate: Callable[[], None]
    unregister_dispatch_commit_hook: Callable[[], None]
    unregister_step_complete_listener: Callable[[], None]
