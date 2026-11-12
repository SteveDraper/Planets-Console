"""Compute request, mutable node state, and caller-visible handles."""

from __future__ import annotations

import threading
import time
from dataclasses import KW_ONLY, dataclass, field
from typing import Literal, get_args

from api.analytics.export_context import AnalyticQueryContext
from api.compute.constants import ENSURE_WAIT_TIMEOUT_SEC
from api.compute.errors import ComputeWaitTimeoutError
from api.compute.orchestration_bundle import OrchestrationBundle
from api.compute.priority_band import ComputePriorityBand, ComputeRequestBand, highest_band
from api.compute.scope import ComputeScope, format_compute_scope_key
from api.compute.submission_open import SubmissionOpen

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

_REQUEST_BANDS: tuple[ComputeRequestBand, ...] = get_args(ComputeRequestBand)


@dataclass(frozen=True)
class ComputeRequest:
    """One orchestrator submission for a compute scope.

    ``priority_band`` is the standing band the request raises on its own
    scope. ``stream_attached`` is never requested: a node derives it from a
    live shell stream watching it or a dependent.
    """

    scope: ComputeScope
    step_kind: str | None = None
    priority_band: ComputeRequestBand = "background"
    force_fresh: bool = False
    bundle: OrchestrationBundle | None = None
    ctx: AnalyticQueryContext | None = None
    # Root turn and backfill choice. None until submission entry resolves it.
    # A resubmitted hop passes the pair it was planned under. An explicit open
    # turn on that pair wins over the scope turn.
    submission_open: SubmissionOpen | None = None

    def __post_init__(self) -> None:
        if self.priority_band not in _REQUEST_BANDS:
            raise ValueError(
                f"ComputeRequest priority_band must be one of {_REQUEST_BANDS}, "
                f"got {self.priority_band!r}"
            )

    def resolved_bundle(self) -> OrchestrationBundle | None:
        """Return the caller-supplied bundle, or build one from ``ctx`` for convenience."""
        if self.bundle is not None:
            return self.bundle
        if self.ctx is not None:
            return OrchestrationBundle.from_context(self.ctx)
        return None


@dataclass(frozen=True)
class ResolvedComputeRequest(ComputeRequest):
    """ComputeRequest whose submission open is already resolved.

    Orchestrator methods that run under the lock take this type.
    ``submission_open`` has no default, so an unresolved request cannot
    cross that boundary.
    """

    _: KW_ONLY
    # ``field()`` keeps this required; the base class default is None.
    submission_open: SubmissionOpen = field()


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


class NodeExecutionBinding:
    """The rule binding a pool item to the execution of its scope that dispatched it.

    Shared by the live node and its diagnostics snapshot, so the worker that
    drops a stale item and the single-step preview that skips it apply one
    definition of stale.
    """

    state: NodeState
    execution_generation: int

    def is_running_execution(self, execution_generation: int) -> bool:
        """Whether this node is ``running`` as the execution ``execution_generation``.

        A pool item is bound to the execution that dispatched it. Abort and a
        ``force_fresh`` replace give the scope a node of a newer generation, so
        the older item no longer matches it.
        """
        return self.state == "running" and self.execution_generation == execution_generation


@dataclass
class ComputeNodeRun(NodeExecutionBinding):
    """Mutable orchestrator state for one compute scope."""

    scope: ComputeScope
    dependency_scopes: tuple[ComputeScope, ...]
    state: NodeState = "waiting_deps"
    profile_step_index: int = 0
    step_index: int = 0
    # The highest band a request for this scope asked for. Dependencies keep
    # the default and take their band from their dependents.
    standing_band: ComputeRequestBand = "background"
    # The band this node would be picked at now. It starts as the standing
    # band and is then written only by each dispatch pass's derivation. A step
    # a worker already picked keeps its picked band on its execution records.
    priority_band: ComputePriorityBand = field(init=False)
    execution_generation: int = 0
    generation_at_submit: int | None = None
    result_wire: object | None = None
    error: BaseException | None = None
    # Analytic park site reason (e.g. SoftTerminalReason); set while ``parked``.
    park_reason: str | None = None
    waiters: list[ComputeHandle] = field(default_factory=list)
    # Leader-retained query context / export services.
    bundle: OrchestrationBundle | None = None
    # Set when in-flight work must finish without persisting or stamping.
    # The worker may finish; persist and stamp are refused, and the step is
    # not retried.
    discard_without_stamp: bool = False
    _: KW_ONLY
    # Root turn and backfill choice of the submission that planned this node.
    # A later submission that roots at this scope replaces the open turn and
    # keeps this backfill choice.
    submission_open: SubmissionOpen
    # The one-shot for this root has already been applied. Hops leave this false.
    open_turn_consumed: bool = False

    def __post_init__(self) -> None:
        self.priority_band = self.standing_band

    def raise_standing_band(self, band: ComputeRequestBand) -> None:
        """Keep the higher of the current standing band and ``band``."""
        self.standing_band = highest_band(self.standing_band, band)

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
