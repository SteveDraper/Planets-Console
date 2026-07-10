"""In-flight pool execution records for compute diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.pools import ComputeBackend, ComputePriorityBand, PoolWorkItem
from api.compute.scope import ComputeScope


@dataclass(frozen=True)
class InFlightPoolExecution:
    """One pool work item that has been dequeued and is not yet complete."""

    scope: ComputeScope
    scope_key: str
    analytic_id: str
    step_kind: str
    step_index: int
    priority_band: ComputePriorityBand
    backend: ComputeBackend
    orchestrator_id: int
    started_at: str


def in_flight_from_pool_item(item: PoolWorkItem) -> InFlightPoolExecution:
    """Build an in-flight record at the dequeue boundary."""
    return InFlightPoolExecution(
        scope=item.scope,
        scope_key=format_compute_scope_key(item.scope),
        analytic_id=item.scope.analytic_id,
        step_kind=item.step_kind,
        step_index=item.step_index,
        priority_band=item.priority_band,
        backend=item.backend,
        orchestrator_id=item.orchestrator_id,
        started_at=datetime.now(UTC).isoformat(),
    )


def in_flight_to_wire(record: InFlightPoolExecution) -> dict[str, object]:
    """Return the camelCase diagnostics snapshot row for one in-flight execution."""
    return {
        "scopeKey": record.scope_key,
        "analyticId": record.analytic_id,
        "stepKind": record.step_kind,
        "stepIndex": record.step_index,
        "priorityBand": record.priority_band,
        "backend": record.backend,
        "orchestratorId": record.orchestrator_id,
        "startedAt": record.started_at,
    }
