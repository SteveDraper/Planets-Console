"""Registry for active fleet table NDJSON streams (in-place reschedule)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.streaming.table_stream.registry import TableStreamRegistry

if TYPE_CHECKING:
    from api.analytics.fleet.fleet_table_stream_controller import FleetTableStreamController

_registry = TableStreamRegistry[FleetTableStreamScope, "FleetTableStreamController"]()


def attach_fleet_table_stream(controller: FleetTableStreamController) -> None:
    _registry.attach(controller.scope, controller)


def detach_fleet_table_stream(stream_token: str) -> None:
    _registry.detach(stream_token, token_getter=lambda controller: controller.stream_token)


def controller_for_scope(scope: FleetTableStreamScope) -> FleetTableStreamController | None:
    return _registry.controller_for_scope(scope)


def reschedule_fleet_table_player(scope: FleetTableStreamScope, player_id: int) -> bool:
    """Cancel and reschedule one player on the open fleet table stream for ``scope``."""
    controller = controller_for_scope(scope)
    if controller is None:
        return False
    return controller.reschedule_player(player_id)


def reschedule_all_fleet_table_players(
    scope: FleetTableStreamScope,
    *,
    force_schedule: bool = False,
) -> bool:
    """Cancel and reschedule every player on the open fleet table stream for ``scope``."""
    controller = controller_for_scope(scope)
    if controller is None:
        return False
    return controller.reschedule_all_players(force_schedule=force_schedule)


def reset_fleet_table_stream_registry_for_tests() -> None:
    _registry.reset_for_tests()
