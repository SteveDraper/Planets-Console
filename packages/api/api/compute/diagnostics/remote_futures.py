"""Wire helpers for remote pool futures in compute diagnostics snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from api.compute.remote_futures import (
    RemotePoolFutureRecord,
    classify_future_state,
    count_remote_futures_by_state,
    future_exception_type,
)
from api.compute.scope import format_compute_scope_key
from api.compute.step_execution_key import StepExecutionKey


def index_remote_futures_by_key(
    records: Sequence[RemotePoolFutureRecord],
) -> dict[StepExecutionKey, RemotePoolFutureRecord]:
    """Index remote futures by step execution (first record wins on collision)."""
    indexed: dict[StepExecutionKey, RemotePoolFutureRecord] = {}
    for record in records:
        indexed.setdefault(record.step_key, record)
    return indexed


def remote_future_to_wire(record: RemotePoolFutureRecord) -> dict[str, object]:
    """Return the camelCase diagnostics row for one remote future."""
    state = classify_future_state(record.future)
    step_key = record.step_key
    row: dict[str, object] = {
        "scopeKey": format_compute_scope_key(step_key.scope),
        "analyticId": step_key.scope.analytic_id,
        "stepKind": step_key.step_kind,
        "stepIndex": step_key.step_index,
        "priorityBand": record.priority_band,
        "backend": record.backend,
        "orchestratorId": step_key.orchestrator_id,
        "submittedAt": record.submitted_at,
        "futureState": state,
    }
    if state == "done":
        row["exceptionType"] = future_exception_type(record.future)
    return row


def build_remote_pool_wire(
    *,
    records: Sequence[RemotePoolFutureRecord],
    interpreter_max_workers: int | None,
    process_max_workers: int | None,
    interpreter_queue_depth: int | None,
    process_queue_depth: int | None,
    dispatch_workers: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Build the ``remotePool`` diagnostics snapshot section."""
    by_backend: dict[str, list[RemotePoolFutureRecord]] = {
        "interpreter": [],
        "process": [],
    }
    for record in records:
        if record.backend in by_backend:
            by_backend[record.backend].append(record)

    wire: dict[str, Any] = {
        "interpreter": {
            "maxWorkers": interpreter_max_workers,
            "queueDepth": interpreter_queue_depth,
            "counts": count_remote_futures_by_state(by_backend["interpreter"]),
            "futures": [remote_future_to_wire(record) for record in by_backend["interpreter"]],
        },
        "process": {
            "maxWorkers": process_max_workers,
            "queueDepth": process_queue_depth,
            "counts": count_remote_futures_by_state(by_backend["process"]),
            "futures": [remote_future_to_wire(record) for record in by_backend["process"]],
        },
    }
    if dispatch_workers is not None:
        wire["dispatch"] = dispatch_workers
    return wire
