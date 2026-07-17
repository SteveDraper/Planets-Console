"""Observer registration and notify surface for ComputeOrchestrator.

Owns listener lists, dispatch gates/hooks, and post-lock callbacks. The
orchestrator remains the public ``register_*`` API via thin wrappers; notify
and drain run through this collaborator so lock-order semantics stay in one place.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeNodeRun

NodeCompleteListener = Callable[[ComputeScope, "ComputeNodeRun"], None]


@dataclass(frozen=True)
class ScopeLifecycleSnapshot:
    """Immutable outcome view captured while the orchestrator lock is held."""

    scope: ComputeScope
    state: Literal["parked", "complete", "failed"]
    execution_generation: int
    result_wire: object | None
    error: BaseException | None


ScopeOutcomeListener = Callable[[ScopeLifecycleSnapshot], None]
StepCompleteListener = Callable[
    [
        ComputeScope,
        "ComputeNodeRun",
        str,
        int,
        Literal["inline", "pool"],
        Literal["success", "failed"],
    ],
    None,
]
# Fired when a node first enters the ready queue (deps satisfied).
ReadyListener = Callable[[ComputeScope, "ComputeNodeRun"], None]
# Fired under the orchestrator lock whenever the ready-queue membership of
# ``state == "ready"`` scopes may have changed. Argument is the current ready
# scopes snapshot. Listeners must not re-enter this orchestrator's condition.
ReadyQueueChangedListener = Callable[[tuple[ComputeScope, ...]], None]
# Fired when an inline step begins execution outside the orchestrator lock.
InlineStartListener = Callable[[ComputeScope, "ComputeNodeRun", str], None]
LifecycleEventKind = Literal[
    "force_fresh_replace",
    "force_fresh_attach",
    "abort",
    "epoch_retry",
    "persist_deferred",
    "step_parked",
    "pool_finish_ignored",
]
# Causal restart / abort / stale-finish events for compute diagnostics.
LifecycleListener = Callable[
    [LifecycleEventKind, ComputeScope, "ComputeNodeRun | None", Mapping[str, Any]],
    None,
]
NodeDispatchGate = Callable[["ComputeNodeRun"], bool]
# Side-effecting accept after all gates pass (e.g. consume a single-step slot).
# Must be idempotent-safe under reject: return False to leave the node ready.
NodeDispatchCommitHook = Callable[["ComputeNodeRun"], bool]
PostLockCallback = Callable[[], None]


class OrchestratorObservers:
    """Listener registration, notify fan-out, and post-lock callback drain."""

    def __init__(self, condition: threading.Condition) -> None:
        self._condition = condition
        self._node_complete_listeners: list[NodeCompleteListener] = []
        self._scope_outcome_listeners: list[ScopeOutcomeListener] = []
        self._step_complete_listeners: list[StepCompleteListener] = []
        self._ready_listeners: list[ReadyListener] = []
        self._ready_queue_listeners: list[ReadyQueueChangedListener] = []
        self._inline_start_listeners: list[InlineStartListener] = []
        self._lifecycle_listeners: list[LifecycleListener] = []
        self._dispatch_gates: list[NodeDispatchGate] = []
        self._dispatch_commit_hooks: list[NodeDispatchCommitHook] = []
        self._post_lock_callbacks: list[PostLockCallback] = []

    @property
    def dispatch_gates(self) -> list[NodeDispatchGate]:
        """Live gate list; callers must hold the orchestrator condition to mutate."""
        return self._dispatch_gates

    @property
    def dispatch_commit_hooks(self) -> list[NodeDispatchCommitHook]:
        """Live commit-hook list; callers must hold the orchestrator condition to mutate."""
        return self._dispatch_commit_hooks

    def schedule_post_lock(self, callback: PostLockCallback) -> None:
        """Append a callback to run after the orchestrator lock is released."""
        self._post_lock_callbacks.append(callback)

    def register_dispatch_gate(
        self,
        gate: NodeDispatchGate,
    ) -> Callable[[], None]:
        with self._condition:
            self._dispatch_gates.append(gate)

        def unregister() -> None:
            with self._condition:
                try:
                    self._dispatch_gates.remove(gate)
                except ValueError:
                    return

        return unregister

    def register_dispatch_commit_hook(
        self,
        hook: NodeDispatchCommitHook,
    ) -> Callable[[], None]:
        with self._condition:
            self._dispatch_commit_hooks.append(hook)

        def unregister() -> None:
            with self._condition:
                try:
                    self._dispatch_commit_hooks.remove(hook)
                except ValueError:
                    return

        return unregister

    def register_node_complete_listener(
        self,
        listener: NodeCompleteListener,
    ) -> Callable[[], None]:
        with self._condition:
            self._node_complete_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._node_complete_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def register_scope_outcome_listener(
        self,
        listener: ScopeOutcomeListener,
    ) -> Callable[[], None]:
        """Observe parked, complete, and failed outcomes after lock release."""
        with self._condition:
            self._scope_outcome_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._scope_outcome_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def register_step_complete_listener(
        self,
        listener: StepCompleteListener,
    ) -> Callable[[], None]:
        with self._condition:
            self._step_complete_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._step_complete_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def register_ready_listener(
        self,
        listener: ReadyListener,
    ) -> Callable[[], None]:
        with self._condition:
            self._ready_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._ready_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def register_ready_queue_listener(
        self,
        listener: ReadyQueueChangedListener,
    ) -> Callable[[], None]:
        with self._condition:
            self._ready_queue_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._ready_queue_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def register_inline_start_listener(
        self,
        listener: InlineStartListener,
    ) -> Callable[[], None]:
        with self._condition:
            self._inline_start_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._inline_start_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def register_lifecycle_listener(
        self,
        listener: LifecycleListener,
    ) -> Callable[[], None]:
        with self._condition:
            self._lifecycle_listeners.append(listener)

        def unregister() -> None:
            with self._condition:
                try:
                    self._lifecycle_listeners.remove(listener)
                except ValueError:
                    return

        return unregister

    def notify_node_complete(self, node: ComputeNodeRun) -> None:
        listeners = tuple(self._node_complete_listeners)
        for listener in listeners:
            self._post_lock_callbacks.append(
                lambda listener=listener, node=node: listener(node.scope, node),
            )

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
        """Push ready-scopes snapshot to depth listeners (caller holds lock)."""
        listeners = tuple(self._ready_queue_listeners)
        if not listeners:
            return
        for listener in listeners:
            listener(ready_scopes)

    def notify_inline_start(self, node: ComputeNodeRun, step_kind: str) -> None:
        with self._condition:
            listeners = tuple(self._inline_start_listeners)
        for listener in listeners:
            listener(node.scope, node, step_kind)

    def notify_step_complete(
        self,
        node: ComputeNodeRun,
        step_kind: str,
        *,
        step_index: int,
        surface: Literal["inline", "pool"],
        terminal_state: Literal["success", "failed"],
    ) -> None:
        """Schedule step-complete listeners with the finished ``step_index``.

        ``step_index`` must be captured before ``_after_step_success`` continues the
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
        node: ComputeNodeRun | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """Schedule causal lifecycle listeners (force_fresh / abort / stale finish)."""
        listeners = tuple(self._lifecycle_listeners)
        if not listeners:
            return
        payload = dict(detail or {})
        for listener in listeners:
            self._post_lock_callbacks.append(
                lambda listener=listener, kind=kind, scope=scope, node=node, payload=payload: (
                    listener(kind, scope, node, payload)
                ),
            )

    def drain_post_lock_callbacks(self) -> None:
        while True:
            with self._condition:
                callbacks = tuple(self._post_lock_callbacks)
                self._post_lock_callbacks.clear()
            if not callbacks:
                return
            for callback in callbacks:
                callback()
