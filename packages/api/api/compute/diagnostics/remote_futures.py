"""Wire helpers for remote pool futures in compute diagnostics snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from api.compute.diagnostics.scope_key import format_compute_scope_key
from api.compute.remote_futures import (
    RemotePoolFutureRecord,
    classify_future_state,
    count_remote_futures_by_state,
    future_exception_type,
    remote_future_key,
)


def index_remote_futures_by_key(
    records: Sequence[RemotePoolFutureRecord],
) -> dict[tuple, RemotePoolFutureRecord]:
    """Index remote futures by execution key (first record wins on collision)."""
    indexed: dict[tuple, RemotePoolFutureRecord] = {}
    for record in records:
        key = remote_future_key(record)
        indexed.setdefault(key, record)
    return indexed


def remote_future_to_wire(record: RemotePoolFutureRecord) -> dict[str, object]:
    """Return the camelCase diagnostics row for one remote future."""
    state = classify_future_state(record.future)
    row: dict[str, object] = {
        "scopeKey": format_compute_scope_key(record.scope),
        "analyticId": record.scope.analytic_id,
        "stepKind": record.step_kind,
        "stepIndex": record.step_index,
        "priorityBand": record.priority_band,
        "backend": record.backend,
        "orchestratorId": record.orchestrator_id,
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
