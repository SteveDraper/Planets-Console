"""Compute request, mutable node state, and caller-visible handles."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from api.analytics.export_context import AnalyticQueryContext
from api.compute.constants import ENSURE_WAIT_TIMEOUT_SEC
from api.compute.errors import ComputeWaitTimeoutError
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.pools import ComputePriorityBand
from api.compute.scope import ComputeScope, format_compute_scope_key

NodeState = Literal[
    "waiting_deps",
    "parked",
    "ready",
    "running",
    "attach_inflight",
    "complete",
    "failed",
]

TERMINAL_NODE_STATES: frozenset[NodeState] = frozenset({"complete", "failed"})


@dataclass(frozen=True)
class ComputeRequest:
    """One orchestrator submission for a compute scope."""

    scope: ComputeScope
    step_kind: str | None = None
    priority_band: ComputePriorityBand = "background"
    force_fresh: bool = False
    bundle: OrchestrationBundle | None = None
    ctx: AnalyticQueryContext | None = None

    def resolved_bundle(self) -> OrchestrationBundle | None:
        """Return the caller-supplied bundle, or build one from ``ctx`` for convenience."""
        if self.bundle is not None:
            return self.bundle
        if self.ctx is not None:
            return OrchestrationBundle.from_context(self.ctx)
        return None


@dataclass
class ComputeHandle:
    """Caller-visible orchestrator handle for one submission."""

    scope: ComputeScope
    _node: ComputeNodeRun
    is_waiter: bool = False
    _waiter_error: BaseException | None = field(default=None, compare=False)
    _condition: threading.Condition | None = field(default=None, compare=False, repr=False)

    @property
    def error(self) -> BaseException | None:
        if self.is_waiter:
            return self._waiter_error
        if self._node.state == "failed":
            return self._node.error
        return None

    @property
    def state(self) -> NodeState:
        if self.is_waiter and not self._node.is_terminal:
            return "attach_inflight"
        return self._node.state

    @property
    def result_wire(self) -> object | None:
        return self._node.result_wire

    def wait(self, timeout: float | None = ENSURE_WAIT_TIMEOUT_SEC) -> ComputeHandle:
        """Block until this scope is terminal on the orchestration plane.

        Default timeout is :data:`ENSURE_WAIT_TIMEOUT_SEC` (300s). Pass ``None`` to
        wait without a deadline. On timeout raises :class:`ComputeWaitTimeoutError`
        for this waiter only -- in-flight DAG work is not cancelled (T1 / #204).

        Soft ``parked`` is not terminal; waiters keep blocking until ``complete`` /
        ``failed`` or timeout.
        """
        condition = self._condition
        if condition is None:
            raise RuntimeError(
                "ComputeHandle.wait requires an orchestrator condition; "
                "use handles returned from ComputeOrchestrator.submit / ensure_scope"
            )

        with condition:
            if not self._node.is_terminal:
                if timeout is None:
                    while not self._node.is_terminal:
                        condition.wait()
                else:
                    deadline = time.monotonic() + timeout
                    while not self._node.is_terminal:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise ComputeWaitTimeoutError(
                                "compute wait for "
                                f"{format_compute_scope_key(self.scope)} "
                                f"did not complete within {timeout}s",
                                scope=self.scope,
                                timeout_sec=timeout,
                            )
                        condition.wait(timeout=remaining)

            error = self.error
            if error is not None:
                raise error
            return self


@dataclass
class ComputeNodeRun:
    """Mutable orchestrator state for one compute scope."""

    scope: ComputeScope
    dependency_scopes: tuple[ComputeScope, ...]
    state: NodeState = "waiting_deps"
    profile_step_index: int = 0
    step_index: int = 0
    priority_band: ComputePriorityBand = "background"
    execution_generation: int = 0
    generation_at_submit: int | None = None
    result_wire: object | None = None
    error: BaseException | None = None
    # Analytic park site reason (e.g. SoftTerminalReason); set while ``parked``.
    park_reason: str | None = None
    waiters: list[ComputeHandle] = field(default_factory=list)
    # Leader-retained query context / export services.
    bundle: OrchestrationBundle | None = None
    # Closes priority adoption once expensive work begins.
    execution_sealed: bool = False

    @property
    def is_terminal(self) -> bool:
        """Whether this node has reached a final outcome.

        ``parked`` is a soft pause, not terminal -- dependents stay blocked
        until an explicit ``force_fresh`` wake.
        """
        return self.state in TERMINAL_NODE_STATES

    @property
    def blocks_readiness_refresh(self) -> bool:
        """Whether readiness refresh should skip this node.

        True once the node is terminal, already running, or parked -- only
        ``waiting_deps`` and ``ready`` nodes need their dependencies re-checked.
        """
        return self.state in {"complete", "failed", "running", "parked"}

    @property
    def allows_priority_adopt(self) -> bool:
        """Whether an attaching request may still upgrade this node's priority band.

        Closed once the node is terminal. Callers also gate on
        ``execution_sealed`` separately.
        """
        return self.state in {"waiting_deps", "parked", "ready", "running"}
