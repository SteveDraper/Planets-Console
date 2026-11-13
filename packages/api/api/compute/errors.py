"""Compute-orchestrator error types."""

from __future__ import annotations

from api.compute.scope import ComputeScope, format_compute_scope_key
from api.compute.step_execution_key import ExecutionRef
from api.errors import ConflictError, ValidationError


class UnresolvedSubmissionOpenError(ValidationError):
    """A submission has no carried open and no bundle to read the backfill choice."""


class ComputeRequesterEndedError(ConflictError):
    """A dependency submit was refused because the execution that queued it has ended.

    Raised by ``ComputeOrchestrator.submit`` before anything is planned, only
    for a request whose ``requester`` is set. The orchestrator sets it on the
    dependency submits a node queues post-lock.
    """

    def __init__(self, requester: ExecutionRef) -> None:
        super().__init__(
            "dependency submit refused: requester "
            f"{format_compute_scope_key(requester.scope)} execution "
            f"{requester.execution_generation} is no longer live"
        )
        self.requester = requester


class ComputeScopeAbortedError(RuntimeError):
    """In-flight compute scope intentionally aborted (e.g. scores row-run cancel).

    On the process-wide singleton DAG, aborting a scope must not cascade
    ``failed`` into dependents (fleet waiting on scores). Dependents stay
    ``waiting_deps`` until a later submit recreates and completes the scope.
    """


class ComputeWaitTimeoutError(TimeoutError):
    """Orchestration-plane ``ComputeHandle.wait`` exceeded its timeout.

    Fails the waiter only -- in-flight DAG work is not cancelled (T1 / #204).
    """

    def __init__(self, message: str, *, scope: ComputeScope, timeout_sec: float) -> None:
        super().__init__(message)
        self.scope = scope
        self.timeout_sec = timeout_sec
