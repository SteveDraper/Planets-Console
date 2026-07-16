"""Orchestrator bindings registered with the compute diagnostics observer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.orchestrator import ComputeOrchestrator


@dataclass(frozen=True)
class BoundOrchestrator:
    """One orchestrator registered with the diagnostics observer.

    When ``game_id`` / ``perspective`` are ``None``, the binding is process-wide
    (singleton orchestrator) and participates in every shell's diagnostic view;
    per-node shell filters still apply.
    """

    orchestrator: ComputeOrchestrator
    game_id: int | None
    perspective: int | None
    ambient_turn: int
    unregister_dispatch_gate: Callable[[], None]
    unregister_dispatch_commit_hook: Callable[[], None]
    unregister_step_complete_listener: Callable[[], None]
    unregister_ready_listener: Callable[[], None]
    unregister_ready_queue_listener: Callable[[], None]
    unregister_inline_start_listener: Callable[[], None]


def bound_matches_shell(bound: BoundOrchestrator, shell: ShellContextKey) -> bool:
    """Return whether ``bound`` should contribute nodes for ``shell``."""
    if bound.game_id is None or bound.perspective is None:
        return True
    return bound.game_id == shell.game_id and bound.perspective == shell.perspective
