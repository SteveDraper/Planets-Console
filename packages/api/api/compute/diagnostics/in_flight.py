"""In-flight pool execution records for compute diagnostics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.pools import ComputeBackend, ComputePriorityBand, PoolWorkItem
from api.compute.scope import ComputeScope

# (orchestrator_id, scope, step_kind, step_index) -- matches a running DAG node.
InFlightExecutionKey = tuple[int, ComputeScope, str, int]


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


def in_flight_execution_key(record: InFlightPoolExecution) -> InFlightExecutionKey:
    """Return the identity key used to match in-flight rows to running DAG nodes."""
    return (record.orchestrator_id, record.scope, record.step_kind, record.step_index)


def filter_live_in_flight(
    records: Sequence[InFlightPoolExecution],
    *,
    running_keys: Iterable[InFlightExecutionKey],
) -> tuple[InFlightPoolExecution, ...]:
    """Return in-flight rows that still match a running DAG node (read-only)."""
    live_keys = frozenset(running_keys)
    return tuple(record for record in records if in_flight_execution_key(record) in live_keys)


def orphan_in_flight_object_ids(
    records: Sequence[InFlightPoolExecution],
    *,
    running_keys: Iterable[InFlightExecutionKey],
) -> set[int]:
    """Return ``id(record)`` for rows that do not match a running DAG node.

    Callers remove only these object ids under lock so concurrently appended
    in-flight rows are not swept away by a stale running-key snapshot.
    """
    live_keys = frozenset(running_keys)
    return {
        id(record)
        for record in records
        if in_flight_execution_key(record) not in live_keys
    }


def remove_in_flight_by_object_ids(
    records: list[InFlightPoolExecution],
    object_ids: set[int],
) -> None:
    """Remove in-flight rows whose ``id`` is in ``object_ids`` (in-place)."""
    if not object_ids:
        return
    records[:] = [record for record in records if id(record) not in object_ids]
