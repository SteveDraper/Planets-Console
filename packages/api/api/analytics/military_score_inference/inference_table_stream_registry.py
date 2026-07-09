"""Registry for active scores inference table streams (in-place reschedule)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.streaming.table_stream.registry import TableStreamRegistry
from api.streaming.table_stream.registry_catalog import register_table_stream_registry

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_table_stream_controller import (
        InferenceTableStreamController,
    )

_registry = TableStreamRegistry[InferenceStreamScope, "InferenceTableStreamController"]()


def attach_inference_table_stream(controller: InferenceTableStreamController) -> None:
    _registry.attach(controller.scope, controller)


def detach_inference_table_stream(stream_token: str) -> None:
    _registry.detach(stream_token, token_getter=lambda controller: controller.stream_token)


def controller_for_scope(scope: InferenceStreamScope) -> InferenceTableStreamController | None:
    return _registry.controller_for_scope(scope)


def wake_inference_table_stream_multiplex(scope: InferenceStreamScope) -> None:
    controller = controller_for_scope(scope)
    if controller is not None:
        controller.wake_multiplex.set()


def reschedule_inference_row(scope: InferenceStreamScope, player_id: int) -> bool:
    """Cancel and reschedule one row on the open table stream for ``scope``."""
    controller = controller_for_scope(scope)
    if controller is None:
        return False
    return controller.reschedule_row(player_id)


def reschedule_all_inference_rows(
    scope: InferenceStreamScope,
    *,
    force_schedule: bool = False,
) -> bool:
    """Cancel and reschedule every row on the open table stream for ``scope``."""
    controller = controller_for_scope(scope)
    if controller is None:
        return False
    return controller.reschedule_all_rows(force_schedule=force_schedule)


def reset_inference_table_stream_registry_for_tests() -> None:
    _registry.reset_for_tests()


def _inference_stream_binding_wire(scope: InferenceStreamScope) -> dict[str, object]:
    return {
        "gameId": scope.game_id,
        "perspective": scope.perspective,
        "turn": scope.turn_number,
    }


register_table_stream_registry(
    "scores",
    _registry,
    binding_wire=_inference_stream_binding_wire,
)
