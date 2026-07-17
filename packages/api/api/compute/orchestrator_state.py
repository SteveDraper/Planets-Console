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
        if self.is_waiter and self._node.state not in {"complete", "failed"}:
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
