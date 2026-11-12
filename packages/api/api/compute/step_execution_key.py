"""Identity of one compute step run by one execution of a scope."""

from __future__ import annotations

from dataclasses import dataclass

from api.compute.scope import ComputeScope


@dataclass(frozen=True)
class StepExecutionKey:
    """One compute step of one execution of ``scope``, on one orchestrator.

    ``execution_generation`` names the execution, so a pool item left by an
    older execution of the same scope and step index has a different key from
    the item its replacement dispatched. ``orchestrator_id`` is the
    orchestrator's pool registration id, or None for an orchestrator with no
    worker pool.
    """

    orchestrator_id: int | None
    scope: ComputeScope
    execution_generation: int
    step_kind: str
    step_index: int
