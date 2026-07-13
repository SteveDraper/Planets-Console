"""Remote (interpreter/process) pool future tracking for the compute worker pool."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from api.compute.profile import ComputeBackend
from api.compute.scope import ComputeScope

ComputePriorityBand = Literal["stream_attached", "interactive_ensure", "background"]
RemoteFutureState = Literal["pending", "running", "done", "cancelled"]

# Matches in-flight / DAG running identity (orchestrator_id, scope, step_kind, step_index).
RemoteFutureKey = tuple[int, ComputeScope, str, int]


@dataclass(frozen=True)
class RemotePoolFutureRecord:
    """One interpreter/process future still tracked by the worker pool."""

    orchestrator_id: int
    scope: ComputeScope
    step_kind: str
    step_index: int
    priority_band: ComputePriorityBand
    backend: ComputeBackend
    future: Future[object]
    submitted_at: str


def remote_future_record(
    *,
    orchestrator_id: int,
    scope: ComputeScope,
    step_kind: str,
    step_index: int,
    priority_band: ComputePriorityBand,
    backend: ComputeBackend,
    future: Future[object],
) -> RemotePoolFutureRecord:
    """Build a remote-future probe at executor submit time."""
    return RemotePoolFutureRecord(
        orchestrator_id=orchestrator_id,
        scope=scope,
        step_kind=step_kind,
        step_index=step_index,
        priority_band=priority_band,
        backend=backend,
        future=future,
        submitted_at=datetime.now(UTC).isoformat(),
    )


def remote_future_key(record: RemotePoolFutureRecord) -> RemoteFutureKey:
    """Return the identity key used to join remote futures to in-flight rows."""
    return (record.orchestrator_id, record.scope, record.step_kind, record.step_index)


def classify_future_state(future: Future[object]) -> RemoteFutureState:
    """Classify a concurrent.futures.Future for diagnostics (non-blocking)."""
    if future.cancelled():
        return "cancelled"
    if future.done():
        return "done"
    if future.running():
        return "running"
    return "pending"


def future_exception_type(future: Future[object]) -> str | None:
    """Return the exception type name when the future finished with an error."""
    if not future.done() or future.cancelled():
        return None
    exc = future.exception()
    if exc is None:
        return None
    return type(exc).__name__


def count_remote_futures_by_state(
    records: Iterable[RemotePoolFutureRecord],
) -> dict[str, int]:
    """Return pending/running/done/cancelled counts for a future set."""
    counts: Counter[str] = Counter(classify_future_state(record.future) for record in records)
    return {
        "pending": int(counts["pending"]),
        "running": int(counts["running"]),
        "done": int(counts["done"]),
        "cancelled": int(counts["cancelled"]),
    }
