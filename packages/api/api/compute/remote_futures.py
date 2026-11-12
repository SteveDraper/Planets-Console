"""Remote (interpreter/process) pool future tracking for the compute worker pool."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from api.compute.profile import ComputeBackend
from api.compute.step_execution_key import StepExecutionKey

ComputePriorityBand = Literal["stream_attached", "interactive_ensure", "background"]
RemoteFutureState = Literal["pending", "running", "done", "cancelled"]


@dataclass(frozen=True)
class RemotePoolFutureRecord:
    """One interpreter/process future still tracked by the worker pool.

    ``step_key`` is the step execution the future runs, which joins it to that
    execution's in-flight row.
    """

    step_key: StepExecutionKey
    priority_band: ComputePriorityBand
    backend: ComputeBackend
    future: Future[object]
    submitted_at: str


def remote_future_record(
    *,
    step_key: StepExecutionKey,
    priority_band: ComputePriorityBand,
    backend: ComputeBackend,
    future: Future[object],
) -> RemotePoolFutureRecord:
    """Build a remote-future probe at executor submit time."""
    return RemotePoolFutureRecord(
        step_key=step_key,
        priority_band=priority_band,
        backend=backend,
        future=future,
        submitted_at=datetime.now(UTC).isoformat(),
    )


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
