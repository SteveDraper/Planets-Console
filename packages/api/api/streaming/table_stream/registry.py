"""Generic registry for active table-stream controllers (in-place reschedule)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Generic, TypeVar

ScopeT = TypeVar("ScopeT")
ControllerT = TypeVar("ControllerT")


class TableStreamRegistry(Generic[ScopeT, ControllerT]):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_controllers: dict[ScopeT, ControllerT] = {}

    def attach(self, scope: ScopeT, controller: ControllerT) -> None:
        with self._lock:
            self._active_controllers[scope] = controller

    def detach(self, stream_token: str, *, token_getter: Callable[[ControllerT], str]) -> None:
        with self._lock:
            for scope, controller in list(self._active_controllers.items()):
                if token_getter(controller) == stream_token:
                    del self._active_controllers[scope]
                    return

    def controller_for_scope(self, scope: ScopeT) -> ControllerT | None:
        with self._lock:
            return self._active_controllers.get(scope)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._active_controllers.clear()
