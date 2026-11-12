"""Generic registry for active table-stream controllers (in-place reschedule).

The registry publishes an immutable ``{scope: controller}`` snapshot. Readers
take no lock, so a scan from under another lock (the orchestrator's, while a
dispatch pass reads stream liveness) never waits on a writer.

Writers build the replacement snapshot outside ``_lock`` and only compare and
swap it under ``_lock``, retrying when another writer published first. Nothing
is allocated while ``_lock`` is held, so a detach that runs from a generator
``finally`` during garbage collection cannot re-enter a held lock or lose an
update.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Generic, TypeVar

ScopeT = TypeVar("ScopeT")
ControllerT = TypeVar("ControllerT")


class TableStreamRegistry(Generic[ScopeT, ControllerT]):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controllers: Mapping[ScopeT, ControllerT] = MappingProxyType({})

    def attach(self, scope: ScopeT, controller: ControllerT) -> None:
        """Attach ``controller`` for ``scope``, replacing any controller already there."""
        while True:
            current = self._controllers
            replacement = MappingProxyType({**current, scope: controller})
            if self._compare_and_swap(current, replacement):
                return

    def detach(self, stream_token: str, *, token_getter: Callable[[ControllerT], str]) -> None:
        """Detach the first controller whose stream token is ``stream_token``, if any."""
        while True:
            current = self._controllers
            detached_scope = next(
                (
                    scope
                    for scope, controller in current.items()
                    if token_getter(controller) == stream_token
                ),
                None,
            )
            if detached_scope is None:
                return
            replacement = MappingProxyType(
                {
                    scope: controller
                    for scope, controller in current.items()
                    if scope != detached_scope
                }
            )
            if self._compare_and_swap(current, replacement):
                return

    def items(self) -> tuple[tuple[ScopeT, ControllerT], ...]:
        """Every attached ``(scope, controller)`` pair, from one published snapshot."""
        return tuple(self._controllers.items())

    def controller_for_scope(self, scope: ScopeT) -> ControllerT | None:
        return self._controllers.get(scope)

    def list_active_scopes(self) -> tuple[ScopeT, ...]:
        return tuple(self._controllers)

    def reset_for_tests(self) -> None:
        empty: Mapping[ScopeT, ControllerT] = MappingProxyType({})
        with self._lock:
            self._controllers = empty

    def _compare_and_swap(
        self,
        expected: Mapping[ScopeT, ControllerT],
        replacement: Mapping[ScopeT, ControllerT],
    ) -> bool:
        with self._lock:
            if self._controllers is not expected:
                return False
            self._controllers = replacement
            return True
