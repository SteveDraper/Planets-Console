"""Identity of one execution of a scope, and of one compute step it runs."""

from __future__ import annotations

from dataclasses import dataclass

from api.compute.scope import ComputeScope


@dataclass(frozen=True)
class ExecutionRef:
    """One execution of ``scope``, named by its ``execution_generation``.

    Abort and a ``force_fresh`` replace end an execution: the scope's node is
    then failed, or a newer generation, so the reference no longer names a
    live execution.
    """

    scope: ComputeScope
    execution_generation: int


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
