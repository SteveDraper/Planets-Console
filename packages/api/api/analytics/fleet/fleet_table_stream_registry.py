"""Registry for active fleet table NDJSON streams (in-place reschedule)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope

if TYPE_CHECKING:
    from api.analytics.fleet.fleet_table_stream_controller import FleetTableStreamController

_registry_lock = threading.Lock()
_active_controllers: dict[FleetTableStreamScope, FleetTableStreamController] = {}


def attach_fleet_table_stream(controller: FleetTableStreamController) -> None:
    with _registry_lock:
        _active_controllers[controller.scope] = controller


def detach_fleet_table_stream(stream_token: str) -> None:
    with _registry_lock:
        for scope, controller in list(_active_controllers.items()):
            if controller.stream_token == stream_token:
                del _active_controllers[scope]
                return


def controller_for_scope(scope: FleetTableStreamScope) -> FleetTableStreamController | None:
    with _registry_lock:
        return _active_controllers.get(scope)


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
    with _registry_lock:
        _active_controllers.clear()
