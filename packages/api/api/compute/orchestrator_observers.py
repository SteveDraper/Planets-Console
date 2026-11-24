"""Observer registration and notify surface for ComputeOrchestrator.

Owns listener lists, dispatch gates/hooks, and post-lock callbacks. Callers
register via ``ComputeOrchestrator.observers.register_*`` so lock-order
semantics stay in one place without thin wrappers on the orchestrator.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, get_args

from api.compute.errors import ComputeScopeAbortedError, NestedBlockingWaitError
from api.compute.profile import StepSurface
from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.compute.orchestrator_state import ComputeNodeRun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScopeLifecycleSnapshot:
    """Immutable outcome view captured while the orchestrator lock is held."""

    scope: ComputeScope
    state: Literal["parked", "complete", "failed"]
    execution_generation: int
    result_wire: object | None
    error: BaseException | None
    # Analytic park site string from the step's ``park`` outcome; None when not parked.
    park_reason: str | None = None
    # Profile position at settlement, so diagnostics can name the failed step.
    step_index: int | None = None
    profile_step_index: int | None = None

    @property
    def is_intentional_abort(self) -> bool:
        """Whether the node failed because something ended it on purpose.

        An abort (an explicit cancel, a settle, or a stopped execution nothing
        needs) fails with ``ComputeScopeAbortedError``. It is not a row error:
        whoever ended the node also reschedules or tears down the row it served.
        """
        return self.state == "failed" and isinstance(self.error, ComputeScopeAbortedError)


ScopeOutcomeListener = Callable[[ScopeLifecycleSnapshot], None]
StepCompleteListener = Callable[
    [
        ComputeScope,
        "ComputeNodeRun",
        str,
        int,
        StepSurface,
        Literal["success", "failed"],
    ],
    None,
]
# Fired when a node first enters the ready queue (deps satisfied).
ReadyListener = Callable[[ComputeScope, "ComputeNodeRun"], None]
# Fired under the orchestrator lock whenever the ready-queue membership of
# ``state == "ready"`` scopes may have changed. Argument is the current ready
# scopes snapshot. Listeners must not re-enter this orchestrator's condition.
# A listener that raises is logged and contained: it cannot abort the
# transition that changed the queue.
ReadyQueueChangedListener = Callable[[tuple[ComputeScope, ...]], None]
# Fired when an inline step begins execution outside the orchestrator lock.
# A listener that raises is logged and contained: the step still runs.
InlineStartListener = Callable[[ComputeScope, "ComputeNodeRun", str], None]
# A step item left unapplied: ``pool_item_dropped`` when a worker picks a pool
# item and drops it without running its step, ``pool_finish_ignored`` when a
# pool step finishes after its execution ended, and ``inline_finish_ignored``
# when an inline step does. ``StepItemIgnoredReason`` says why.
StepItemIgnoredKind = Literal["pool_item_dropped", "pool_finish_ignored", "inline_finish_ignored"]
STEP_ITEM_IGNORED_KINDS: frozenset[StepItemIgnoredKind] = frozenset(get_args(StepItemIgnoredKind))


class StepItemIgnoredReason(StrEnum):
    """Why a step item was left unapplied: the ``reason`` of its ignored-item record.

    The first three say the item's execution is no longer running.
    ``START_REFUSED`` says it was running, and the start-or-requeue gate
    ended it at the pick or the post-build re-check (``pool_item_dropped`` only).
    """

    MISSING_NODE = "missing_node"
    # The item's execution is the node's, and it has ended.
    NODE_NOT_RUNNING = "node_not_running"
    # The node is a newer execution than the item's.
    STALE_EXECUTION = "stale_execution"
    START_REFUSED = "start_refused"


LifecycleEventKind = (
    Literal[
        "force_fresh_replace",
        "force_fresh_attach",
        "abort",
        "epoch_retry",
        "persist_deferred",
        "persist_recovery_exhausted",
        "step_parked",
        "dependency_submit_refused",
    ]
    | StepItemIgnoredKind
)
# Causal restart / abort / stale-item events for compute diagnostics.
# ``execution_generation`` / ``step_kind`` / ``step_index`` are the canonical
# step identity for the event (e.g. the step that was aborted, or the pool
# item that was ignored, whose execution may be older than the node's);
# ``detail`` carries only kind-specific auxiliary fields, never step identity.
LifecycleListener = Callable[
    [
        LifecycleEventKind,
        ComputeScope,
        "ComputeNodeRun | None",
        int,
        str | None,
        int | None,
        Mapping[str, Any],
    ],
    None,
]
# Side-effect-free admission check for one ready node. A dispatch pass asks
# each gate once per node; a gate must never admit more because of a commit
# earlier in the same pass.
NodeDispatchGate = Callable[["ComputeNodeRun"], bool]
# Side-effecting accept after all gates pass (e.g. consume a single-step slot).
# Must be idempotent-safe under reject: return False to leave the node ready.
# Like a gate, it must never admit more because of a commit earlier in the pass.
NodeDispatchCommitHook = Callable[["ComputeNodeRun"], bool]
PostLockCallback = Callable[[], None]
# Names the kind of observer callback in a failure log.
ObserverRole = Literal["Post-lock callback", "Ready-queue listener", "Inline-start listener"]


def _call_each_contained[*Args](
    callbacks: Iterable[Callable[[*Args], None]],
    args: tuple[*Args],
    role: ObserverRole,
) -> None:
    """Call every callback with ``args``, logging each failure and running the rest.

    A failure is logged with its stack trace and the callback named, and is
    not re-raised. An observer callback never fails the work that notified
    it: the notifier may be partway through a node transition under the
    orchestrator lock, or be a pool worker that must keep running. Only
    ``Exception`` is contained, so an interrupt still propagates.
    """
    for callback in callbacks:
        try:
            callback(*args)
        except Exception:
            logger.exception("%s %r failed; running the rest", role, callback)


class _DrainState(threading.local):
    """What this thread is doing for one orchestrator: draining its queue, or running a step."""

    def __init__(self) -> None:
        self.is_draining = False
        self.steps_running = 0


class OrchestratorObservers:
    """Listener registration, notify fan-out, and post-lock callback drain."""

    def __init__(self, condition: threading.Condition) -> None:
        self._condition = condition
        self._scope_outcome_listeners: list[ScopeOutcomeListener] = []
        self._step_complete_listeners: list[StepCompleteListener] = []
        self._ready_listeners: list[ReadyListener] = []
        self._ready_queue_listeners: list[ReadyQueueChangedListener] = []
        self._inline_start_listeners: list[InlineStartListener] = []
        self._lifecycle_listeners: list[LifecycleListener] = []
        self._dispatch_gates: list[NodeDispatchGate] = []
        self._dispatch_commit_hooks: list[NodeDispatchCommitHook] = []
        self._post_lock_callbacks: list[PostLockCallback] = []
        self._drain_state = _DrainState()

    @property
    def condition(self) -> threading.Condition:
        """The orchestrator condition this surface guards its lists and queue with."""
        return self._condition

    def reject_blocking_wait(self, operation: str) -> None:
        """Raise when this thread is inside a drain or a step of this orchestrator.

        Called at the entry of every blocking wait (``ensure_scopes``,
        ``run_until_idle``, ``ComputeHandle.wait``), before it plans or waits,
        whatever the state of the work it would wait on.
        """
        state = self._drain_state
        if state.is_draining or state.steps_running:
            raise NestedBlockingWaitError(operation)

    @contextmanager
    def running_step(self) -> Iterator[None]:
        """Mark this thread as running one of this orchestrator's steps (wire build or step)."""
        state = self._drain_state
        state.steps_running += 1
        try:
            yield
        finally:
            state.steps_running -= 1

    @property
    def dispatch_gates(self) -> list[NodeDispatchGate]:
        """Live gate list; callers must hold the orchestrator condition to mutate."""
        return self._dispatch_gates

    @property
    def dispatch_commit_hooks(self) -> list[NodeDispatchCommitHook]:
        """Live commit-hook list; callers must hold the orchestrator condition to mutate."""
        return self._dispatch_commit_hooks

    def _register[Callback](
        self,
        registry: list[Callback],
        callback: Callback,
    ) -> Callable[[], None]:
        """Add ``callback`` to ``registry`` under the condition; return an idempotent unregister."""
        with self._condition:
            registry.append(callback)

        def unregister() -> None:
            with self._condition:
                try:
                    registry.remove(callback)
                except ValueError:
                    return

        return unregister

    def schedule_post_lock(self, callback: PostLockCallback) -> None:
        """Append a callback to run after the orchestrator lock is released.

        Caller holds the orchestrator condition. The callback runs from
        ``drain_post_lock_callbacks`` with the condition released.
        """
        self._post_lock_callbacks.append(callback)

    def register_dispatch_gate(
        self,
        gate: NodeDispatchGate,
    ) -> Callable[[], None]:
        return self._register(self._dispatch_gates, gate)

    def register_dispatch_commit_hook(
        self,
        hook: NodeDispatchCommitHook,
    ) -> Callable[[], None]:
        return self._register(self._dispatch_commit_hooks, hook)

    def register_scope_outcome_listener(
        self,
        listener: ScopeOutcomeListener,
    ) -> Callable[[], None]:
        """Observe parked, complete, and failed outcomes after lock release."""
        return self._register(self._scope_outcome_listeners, listener)

    def register_step_complete_listener(
        self,
        listener: StepCompleteListener,
    ) -> Callable[[], None]:
        return self._register(self._step_complete_listeners, listener)

    def register_ready_listener(
        self,
        listener: ReadyListener,
    ) -> Callable[[], None]:
        return self._register(self._ready_listeners, listener)

    def register_ready_queue_listener(
        self,
        listener: ReadyQueueChangedListener,
    ) -> Callable[[], None]:
        return self._register(self._ready_queue_listeners, listener)

    def register_inline_start_listener(
        self,
        listener: InlineStartListener,
    ) -> Callable[[], None]:
        return self._register(self._inline_start_listeners, listener)

    def register_lifecycle_listener(
        self,
        listener: LifecycleListener,
    ) -> Callable[[], None]:
        return self._register(self._lifecycle_listeners, listener)

    def notify_scope_outcome(self, node: ComputeNodeRun) -> None:
        """Schedule an immutable terminal-or-parked outcome snapshot."""
        if node.state not in {"parked", "complete", "failed"}:
            raise ValueError(f"Scope outcome requires parked or terminal node, got {node.state!r}")
        snapshot = ScopeLifecycleSnapshot(
            scope=node.scope,
            state=node.state,
            execution_generation=node.execution_generation,
            result_wire=node.result_wire,
            error=node.error,
            park_reason=node.park_reason if node.state == "parked" else None,
            step_index=node.step_index,
            profile_step_index=node.profile_step_index,
        )
        for listener in tuple(self._scope_outcome_listeners):
            self._post_lock_callbacks.append(
                lambda listener=listener, snapshot=snapshot: listener(snapshot),
            )

    def notify_ready(self, node: ComputeNodeRun) -> None:
        listeners = tuple(self._ready_listeners)
        for listener in listeners:
            self._post_lock_callbacks.append(
                lambda listener=listener, node=node: listener(node.scope, node),
            )

    def notify_ready_queue_changed(self, ready_scopes: tuple[ComputeScope, ...]) -> None:
        """Push the ready-scopes snapshot to every ready-queue listener (caller holds lock).

        Never raises for a listener, so the transition that changed the queue
        always completes.
        """
        _call_each_contained(
            tuple(self._ready_queue_listeners), (ready_scopes,), "Ready-queue listener"
        )

    def notify_inline_start(self, node: ComputeNodeRun, step_kind: str) -> None:
        """Tell every inline-start listener the step is starting; never raises for a listener."""
        with self._condition:
            listeners = tuple(self._inline_start_listeners)
        _call_each_contained(listeners, (node.scope, node, step_kind), "Inline-start listener")

    def notify_step_complete(
        self,
        node: ComputeNodeRun,
        step_kind: str,
        *,
        step_index: int,
        surface: StepSurface,
        terminal_state: Literal["success", "failed"],
    ) -> None:
        """Schedule step-complete listeners with the finished ``step_index``.

        ``step_index`` must be captured before ``_apply_step_result`` continues the
        node (which advances ``node.step_index`` before post-lock drain).
        """
        listeners = tuple(self._step_complete_listeners)
        for listener in listeners:

            def _notify(
                listener=listener,
                node=node,
                step_kind=step_kind,
                step_index=step_index,
                surface=surface,
                terminal_state=terminal_state,
            ):
                listener(
                    node.scope,
                    node,
                    step_kind,
                    step_index,
                    surface,
                    terminal_state,
                )

            self._post_lock_callbacks.append(_notify)

    def notify_lifecycle(
        self,
        kind: LifecycleEventKind,
        scope: ComputeScope,
        *,
        execution_generation: int,
        node: ComputeNodeRun | None = None,
        step_kind: str | None = None,
        step_index: int | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """Schedule causal lifecycle listeners (force_fresh / abort / stale pool item / refusal).

        ``execution_generation`` / ``step_kind`` / ``step_index`` are the
        canonical step identity for this event; every call site passes them
        explicitly rather than burying a differently-named equivalent inside
        ``detail``. ``detail`` is reserved for kind-specific auxiliary fields
        (reason, prior state, and similar).
        """
        listeners = tuple(self._lifecycle_listeners)
        if not listeners:
            return
        payload = dict(detail or {})
        for listener in listeners:

            def _notify(
                listener=listener,
                kind=kind,
                scope=scope,
                node=node,
                execution_generation=execution_generation,
                step_kind=step_kind,
                step_index=step_index,
                payload=payload,
            ):
                listener(kind, scope, node, execution_generation, step_kind, step_index, payload)

            self._post_lock_callbacks.append(_notify)

    def drain_post_lock_callbacks(self) -> None:
        """Run queued callbacks, and any they schedule, until the queue is empty.

        A call on a thread that is already draining this queue returns at
        once: what the caller queued is in the shared queue, and the active
        drain's loop claims it next. So drains never nest on one thread, and
        an inline chain, whose every node schedules its successor's dispatch
        pass from a callback, runs at constant stack depth. A caller inside a
        drain therefore returns before the callbacks it queued have run.

        Each drain claims everything queued so far in one lock hold and runs
        it in order. Failures are contained as for every observer fan-out
        (``_call_each_contained``): the batch mixes callbacks scheduled by
        other nodes and threads, so the draining thread is not their owner,
        and a pool worker draining after its own step must keep running.
        Persist failures are handled inside their own callback. If anything
        else escapes (a ``BaseException``), the claimed callbacks not yet
        started go back to the head of the queue, in order, for the next
        drain; the one that raised is not run again.
        """
        if self._drain_state.is_draining:
            return
        self._drain_state.is_draining = True
        try:
            while self._drain_one_batch():
                pass
        finally:
            self._drain_state.is_draining = False

    def _drain_one_batch(self) -> bool:
        """Claim and run every queued callback; return whether there were any."""
        with self._condition:
            batch = deque(self._post_lock_callbacks)
            self._post_lock_callbacks.clear()
        if not batch:
            return False
        try:
            # Popped one at a time, so what is left in ``batch`` is exactly
            # what has not started when a ``BaseException`` escapes.
            unstarted = (batch.popleft() for _ in range(len(batch)))
            _call_each_contained(unstarted, (), "Post-lock callback")
        finally:
            if batch:
                with self._condition:
                    self._post_lock_callbacks[:0] = batch
        return True
