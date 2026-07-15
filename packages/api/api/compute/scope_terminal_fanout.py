"""Process-wide fan-out for compute scope terminal outcomes.

Scores ``InferenceRowScheduler`` registers here as its sole terminal path so
completions on any orchestrator binding (stream or peer, e.g. fleet DAG
``tier_solve``) reach the adapter. Fleet table stream keeps a local orchestrator
listener and does not use this registry.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.compute.scope import ComputeScope

if TYPE_CHECKING:
    from api.compute.orchestrator import ComputeNodeRun

ScopeTerminalListener = Callable[[ComputeScope, "ComputeNodeRun"], None]


@dataclass(frozen=True)
class _RegisteredListener:
    analytic_id: str | None
    listener: ScopeTerminalListener


class ProcessScopeTerminalFanout:
    """Register and notify process-wide scope-terminal listeners."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: list[_RegisteredListener] = []

    def register(
        self,
        listener: ScopeTerminalListener,
        *,
        analytic_id: str | None = None,
    ) -> Callable[[], None]:
        """Register a listener; optional ``analytic_id`` filters notifications."""
        registered = _RegisteredListener(analytic_id=analytic_id, listener=listener)
        with self._lock:
            self._listeners.append(registered)

        def unregister() -> None:
            with self._lock:
                try:
                    self._listeners.remove(registered)
                except ValueError:
                    return

        return unregister

    def notify(self, scope: ComputeScope, node: ComputeNodeRun) -> None:
        """Invoke matching listeners for a terminal node (complete or failed)."""
        with self._lock:
            listeners = tuple(self._listeners)
        for registered in listeners:
            if registered.analytic_id is not None and registered.analytic_id != scope.analytic_id:
                continue
            registered.listener(scope, node)

    def reset_for_tests(self) -> None:
        """Drop all listeners (tests only)."""
        with self._lock:
            self._listeners.clear()


_PROCESS_SCOPE_TERMINAL_FANOUT = ProcessScopeTerminalFanout()


def get_process_scope_terminal_fanout() -> ProcessScopeTerminalFanout:
    """Return the process-wide scope-terminal fan-out singleton."""
    return _PROCESS_SCOPE_TERMINAL_FANOUT


def register_process_scope_terminal_listener(
    listener: ScopeTerminalListener,
    *,
    analytic_id: str | None = None,
) -> Callable[[], None]:
    """Register a process-wide scope-terminal listener."""
    return _PROCESS_SCOPE_TERMINAL_FANOUT.register(listener, analytic_id=analytic_id)


def notify_process_scope_terminal(scope: ComputeScope, node: ComputeNodeRun) -> None:
    """Notify process-wide listeners that ``scope`` reached a terminal outcome."""
    _PROCESS_SCOPE_TERMINAL_FANOUT.notify(scope, node)


def reset_process_scope_terminal_fanout_for_tests() -> None:
    """Clear process-wide terminal listeners (tests only)."""
    _PROCESS_SCOPE_TERMINAL_FANOUT.reset_for_tests()
