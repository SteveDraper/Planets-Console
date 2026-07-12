"""Registry for active scores inference table streams (in-place reschedule)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.military_score_inference.inference_stream_domain_events import (
    InferenceStreamDomainEvent,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.streaming.table_stream.registry import TableStreamRegistry

if TYPE_CHECKING:
    from api.analytics.military_score_inference.inference_table_stream_controller import (
        InferenceTableStreamController,
    )

_registry = TableStreamRegistry[InferenceStreamScope, "InferenceTableStreamController"]()


def get_inference_table_stream_registry() -> TableStreamRegistry[
    InferenceStreamScope, "InferenceTableStreamController"
]:
    """Return the process-wide scores inference table-stream registry."""
    return _registry


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


def deliver_inference_domain_event_to_open_stream(
    session: InferenceRowStreamSession,
    event: InferenceStreamDomainEvent,
) -> None:
    """Deliver a domain event to the open table stream for ``session``'s scope.

    When no controller is attached, enqueue on the session queue only. Otherwise
    the controller routes bound vs unbound (pending wire) multiplex delivery.
    """
    scope = InferenceStreamScope(
        game_id=session.game_id,
        perspective=session.perspective,
        turn_number=session.turn_number,
    )
    controller = controller_for_scope(scope)
    if controller is None:
        session.event_queue.put(event)
        return
    controller.deliver_domain_event(session, event)


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
