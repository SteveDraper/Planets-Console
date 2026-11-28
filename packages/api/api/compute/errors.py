"""Compute-orchestrator error types."""

from __future__ import annotations

from api.compute.scope import ComputeScope, format_compute_scope_key
from api.compute.step_execution_key import ExecutionRef
from api.errors import ConflictError, CoreAPIError, ValidationError


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


class PersistDependencyRecoveryExhaustedError(CoreAPIError):
    """A node deferred onto a dependency again although its last recovery changed nothing.

    The node's previous persist-deferred recovery recreated ``recovery_scope``
    at the same invalidation generation, the recreation completed, and the
    persist still could not land. Recreating it again would loop, so the node
    fails. It is not an abort, so the failure cascades to waiting dependents;
    a later submit replaces the nodes.
    """

    def __init__(self, recovery_scope: ComputeScope) -> None:
        super().__init__(
            "persist-deferred recovery exhausted: recreating "
            f"{format_compute_scope_key(recovery_scope)} did not let the persist land"
        )
        self.recovery_scope = recovery_scope


class ComputeExecutionEndedError(RuntimeError):
    """A job-wire build found that the node execution it builds for has ended.

    A builder raises it, through its ``is_execution_live`` probe, rather than
    change shared state on behalf of an execution that can no longer run the
    step. The orchestrator applies a step failure only to an execution that is
    still running, so this one changes no node, and the step never runs.
    """


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


class NestedBlockingWaitError(CoreAPIError):
    """A blocking orchestrator wait was called inside a post-lock drain or a step.

    A wait there could block on work that only the suspended drain on the same
    thread would run, and leaf steps never wait by design. Raised before any
    planning, turn fetch or condition wait.
    """

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation} cannot run inside a compute post-lock drain or a compute step"
        )
        self.operation = operation


class NestedRootPlanSubmitError(CoreAPIError):
    """A submission was called on a thread with an open root-plan block of this orchestrator.

    Root plans hold their on-walk assumptions while they are open, so work
    planned under one would read the outer plan's assumed evidence. Work that
    must start compute from inside a root-plan block goes through
    ``run_after_root_plans``, which runs it once every block on the thread
    has closed. Raised before anything is planned or fetched.
    """

    def __init__(self, operation: str) -> None:
        super().__init__(f"{operation} cannot run inside an open compute root plan")
        self.operation = operation
