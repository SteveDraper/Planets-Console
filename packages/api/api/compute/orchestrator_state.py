"""Mutable compute-node state and caller-visible handles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.pools import ComputePriorityBand
from api.compute.scope import ComputeScope

NodeState = Literal[
    "waiting_deps",
    "parked",
    "ready",
    "running",
    "attach_inflight",
    "complete",
    "failed",
]


@dataclass
class ComputeHandle:
    """Caller-visible orchestrator handle for one submission."""

    scope: ComputeScope
    _node: ComputeNodeRun
    is_waiter: bool = False
    _waiter_error: BaseException | None = field(default=None, compare=False)

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
    waiters: list[ComputeHandle] = field(default_factory=list)
    # Leader-retained query context / export services.
    bundle: OrchestrationBundle | None = None
    # Closes priority adoption once expensive work begins.
    execution_sealed: bool = False
    # One orchestrator-issued wake per soft-park episode when a dependent is
    # waiting_deps. Prevents park→wake→park thrash while still breaking the
    # parked-ENSURE idle hang (empty ready/in-flight, no CPU).
    park_auto_wake_issued: bool = False

    @property
    def is_terminal(self) -> bool:
        """Whether this node has reached a final outcome.

        ``parked`` is a soft pause, not terminal -- dependents stay blocked
        until an explicit ``force_fresh`` wake.
        """
        return self.state in {"complete", "failed"}

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
