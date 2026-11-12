"""In-flight pool execution records for compute diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from api.compute.orchestrator import OrchestratorNodeSnapshot
from api.compute.pools import BandedWorkItem, ComputeBackend
from api.compute.priority_band import ComputePriorityBand
from api.compute.scope import format_compute_scope_key
from api.compute.step_execution_key import StepExecutionKey


@dataclass(frozen=True)
class InFlightPoolExecution:
    """One pool work item that has been dequeued and is not yet complete.

    ``step_key`` names the execution that dispatched the item, so a stale
    item's row never matches the running step of a newer execution of its
    scope. ``priority_band`` is the band the item was picked at; it does not
    follow later band changes on its node.
    """

    step_key: StepExecutionKey
    priority_band: ComputePriorityBand
    backend: ComputeBackend
    started_at: str


def in_flight_from_pool_item(picked: BandedWorkItem) -> InFlightPoolExecution:
    """Build an in-flight record at the dequeue boundary, at the band ``picked`` was picked at."""
    item = picked.item
    return InFlightPoolExecution(
        step_key=item.step_key,
        priority_band=picked.priority_band,
        backend=item.backend,
        started_at=datetime.now(UTC).isoformat(),
    )


def in_flight_to_wire(record: InFlightPoolExecution) -> dict[str, object]:
    """Return the camelCase diagnostics snapshot row for one in-flight execution."""
    step_key = record.step_key
    return {
        "scopeKey": format_compute_scope_key(step_key.scope),
        "analyticId": step_key.scope.analytic_id,
        "stepKind": step_key.step_kind,
        "stepIndex": step_key.step_index,
        "executionGeneration": step_key.execution_generation,
        "priorityBand": record.priority_band,
        "backend": record.backend,
        "orchestratorId": step_key.orchestrator_id,
        "startedAt": record.started_at,
    }


def filter_live_in_flight(
    records: Sequence[InFlightPoolExecution],
    *,
    running_keys: Iterable[StepExecutionKey],
) -> tuple[InFlightPoolExecution, ...]:
    """Return in-flight rows that still match a running DAG node (read-only)."""
    live_keys = frozenset(running_keys)
    return tuple(record for record in records if record.step_key in live_keys)


def orphan_in_flight_object_ids(
    records: Sequence[InFlightPoolExecution],
    *,
    running_keys: Iterable[StepExecutionKey],
) -> set[int]:
    """Return ``id(record)`` for rows that do not match a running DAG node.

    Callers remove only these object ids under lock so concurrently appended
    in-flight rows are not swept away by a stale running-key snapshot.
    """
    live_keys = frozenset(running_keys)
    return {id(record) for record in records if record.step_key not in live_keys}


def remove_in_flight_by_object_ids(
    records: list[InFlightPoolExecution],
    object_ids: set[int],
) -> None:
    """Remove in-flight rows whose ``id`` is in ``object_ids`` (in-place)."""
    if not object_ids:
        return
    records[:] = [record for record in records if id(record) not in object_ids]


def clear_in_flight_for_step(
    records: list[InFlightPoolExecution],
    step_key: StepExecutionKey,
) -> bool:
    """Remove the row for ``step_key``. Return whether a row was removed."""
    for index, record in enumerate(records):
        if record.step_key == step_key:
            del records[index]
            return True
    return False


def running_in_flight_keys_for_nodes(
    *,
    orchestrator_id: int,
    nodes: Sequence[OrchestratorNodeSnapshot],
    step_kind_for_node: Callable[[OrchestratorNodeSnapshot], str | None],
) -> set[StepExecutionKey]:
    """Collect the step keys of ``running`` nodes on one orchestrator."""
    keys: set[StepExecutionKey] = set()
    for node in nodes:
        if node.state != "running":
            continue
        step_kind = step_kind_for_node(node)
        if step_kind is None:
            continue
        keys.add(
            StepExecutionKey(
                orchestrator_id=orchestrator_id,
                scope=node.scope,
                execution_generation=node.execution_generation,
                step_kind=step_kind,
                step_index=node.step_index,
            )
        )
    return keys
