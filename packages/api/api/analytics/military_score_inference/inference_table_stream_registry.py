"""Registry for active scores inference table streams (in-place reschedule)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_table_stream_controller import (
        InferenceTableStreamController,
    )

_registry_lock = threading.Lock()
_active_controllers: dict[InferenceStreamScope, InferenceTableStreamController] = {}


def attach_inference_table_stream(controller: InferenceTableStreamController) -> None:
    with _registry_lock:
        _active_controllers[controller.scope] = controller


def detach_inference_table_stream(stream_token: str) -> None:
    with _registry_lock:
        for scope, controller in list(_active_controllers.items()):
            if controller.stream_token == stream_token:
                del _active_controllers[scope]
                return


def controller_for_scope(scope: InferenceStreamScope) -> InferenceTableStreamController | None:
    with _registry_lock:
        return _active_controllers.get(scope)


def reschedule_inference_row(scope: InferenceStreamScope, player_id: int) -> bool:
    """Cancel and reschedule one row on the open table stream for ``scope``."""
    controller = controller_for_scope(scope)
    if controller is None:
        return False
    return controller.reschedule_row(player_id)


def reschedule_all_inference_rows(scope: InferenceStreamScope) -> bool:
    """Cancel and reschedule every row on the open table stream for ``scope``."""
    controller = controller_for_scope(scope)
    if controller is None:
        return False
    return controller.reschedule_all_rows()


def reset_inference_table_stream_registry_for_tests() -> None:
    with _registry_lock:
        _active_controllers.clear()
