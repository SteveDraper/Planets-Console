"""Compute-orchestrator error types."""

from __future__ import annotations

from api.compute.scope import ComputeScope


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
