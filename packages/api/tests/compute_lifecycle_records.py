"""Record the compute orchestrator's lifecycle events for test assertions."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from api.compute.orchestrator import ComputeOrchestrator
from api.compute.orchestrator_observers import LifecycleEventKind
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.scope import ComputeScope


@dataclass(frozen=True)
class LifecycleRecord:
    """One lifecycle event as its listener received it, with ``detail`` copied at record time."""

    kind: LifecycleEventKind
    scope: ComputeScope
    node: ComputeNodeRun | None
    execution_generation: int
    step_kind: str | None
    step_index: int | None
    detail: Mapping[str, object]


def record_lifecycle(
    orchestrator: ComputeOrchestrator,
    kinds: Collection[LifecycleEventKind] | None = None,
) -> list[LifecycleRecord]:
    """Record each lifecycle event of ``kinds`` (every kind when None) from now on.

    Returns the live list the listener appends to.
    """
    records: list[LifecycleRecord] = []

    def record(
        kind: LifecycleEventKind,
        scope: ComputeScope,
        node: ComputeNodeRun | None,
        execution_generation: int,
        step_kind: str | None,
        step_index: int | None,
        detail: Mapping[str, Any],
    ) -> None:
        if kinds is None or kind in kinds:
            records.append(
                LifecycleRecord(
                    kind=kind,
                    scope=scope,
                    node=node,
                    execution_generation=execution_generation,
                    step_kind=step_kind,
                    step_index=step_index,
                    detail=dict(detail),
                )
            )

    orchestrator.observers.register_lifecycle_listener(record)
    return records


def kinds_and_reasons(records: list[LifecycleRecord]) -> list[tuple[LifecycleEventKind, object]]:
    """``(kind, detail["reason"])`` of each record, for kinds whose detail names a reason."""
    return [(record.kind, record.detail["reason"]) for record in records]
