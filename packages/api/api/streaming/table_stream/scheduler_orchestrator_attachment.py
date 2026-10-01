"""Scheduler-lifetime orchestrator callbacks for one table-stream scheduler.

Fleet and scores both attach to the process orchestrator the same way: one
scope-outcome listener, plus an optional dispatch gate, registered once per
live orchestrator. Stream begin, preempt, and end only mutate scheduler maps.
They do not register or unregister these callbacks, including from a generator
``finally`` that may already hold the orchestrator condition.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from api.compute.orchestrator_observers import NodeDispatchGate, ScopeOutcomeListener

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeOrchestrator


class SchedulerOrchestratorAttachment:
    """One listener and optional gate for the life of a table-stream scheduler.

    ``ensure_registered`` takes the orchestrator condition on first use for the
    current process orchestrator. Call it outside the scheduler lock, and not
    from a caller that already holds that condition. ``shutdown`` unregisters
    both callbacks.
    """

    def __init__(
        self,
        *,
        on_scope_outcome: ScopeOutcomeListener,
        dispatch_gate: NodeDispatchGate | None = None,
    ) -> None:
        self._on_scope_outcome = on_scope_outcome
        self._dispatch_gate = dispatch_gate
        self._init_lock = threading.Lock()
        self._orchestrator: ComputeOrchestrator | None = None
        self._unregister_listener: Callable[[], None] | None = None
        self._unregister_gate: Callable[[], None] | None = None

    def ensure_registered(self) -> None:
        """Register callbacks on the current process orchestrator, once."""
        from api.compute.runtime import get_compute_orchestrator

        orchestrator = get_compute_orchestrator()
        if self._callbacks_current(orchestrator):
            return
        with self._init_lock:
            orchestrator = get_compute_orchestrator()
            if self._orchestrator is not orchestrator:
                # The previous singleton was replaced (test reset). Its callbacks
                # died with it; register on the live orchestrator.
                self._unregister_listener = None
                self._unregister_gate = None
                self._orchestrator = orchestrator
            if self._callbacks_current(orchestrator):
                return
            observers = orchestrator.observers
            if self._unregister_listener is None:
                self._unregister_listener = observers.register_scope_outcome_listener(
                    self._on_scope_outcome
                )
            if self._dispatch_gate is not None and self._unregister_gate is None:
                self._unregister_gate = observers.register_dispatch_gate(self._dispatch_gate)

    def _callbacks_current(self, orchestrator: ComputeOrchestrator) -> bool:
        if self._orchestrator is not orchestrator or self._unregister_listener is None:
            return False
        return self._dispatch_gate is None or self._unregister_gate is not None

    def shutdown(self) -> None:
        """Unregister callbacks. Caller must not hold the scheduler lock."""
        with self._init_lock:
            unregister_listener = self._unregister_listener
            unregister_gate = self._unregister_gate
            self._unregister_listener = None
            self._unregister_gate = None
            self._orchestrator = None
        if unregister_listener is not None:
            unregister_listener()
        if unregister_gate is not None:
            unregister_gate()
