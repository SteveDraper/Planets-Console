"""BFF-facing facade for the compute diagnostics control plane.

Keeps ``api.compute.diagnostics`` internals behind the allowed Core API
service import surface (see ``.cursor/rules/bff.mdc``).
"""

from __future__ import annotations

from typing import Any

from api.compute.diagnostics.controller import (
    compute_diagnostics_enabled,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
)
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.snapshot import snapshot_to_wire

__all__ = [
    "compute_diagnostics_enabled",
    "get_compute_diagnostics_freeze_status",
    "get_compute_diagnostics_snapshot_wire",
    "get_compute_diagnostics_stream_allowlist",
    "reset_compute_diagnostics_for_tests",
    "run_compute_diagnostics_single_step",
    "set_compute_diagnostics_allowlist",
    "set_compute_diagnostics_freeze_armed",
]


def _shell(*, game_id: int, perspective: int, turn: int) -> ShellContextKey:
    return ShellContextKey(game_id=game_id, perspective=perspective, turn=turn)


def get_compute_diagnostics_snapshot_wire(
    *,
    game_id: int,
    perspective: int,
    turn: int,
) -> dict[str, Any]:
    """Return the wire-shaped diagnostics snapshot for one shell context."""
    shell = _shell(game_id=game_id, perspective=perspective, turn=turn)
    controller = get_compute_diagnostics_controller()
    return snapshot_to_wire(controller.snapshot(shell))


def get_compute_diagnostics_freeze_status(
    *,
    game_id: int,
    perspective: int,
    turn: int,
) -> tuple[bool, frozenset[int]]:
    """Return ``(freeze_armed, allowlisted_player_ids)`` for one shell."""
    shell = _shell(game_id=game_id, perspective=perspective, turn=turn)
    return get_compute_diagnostics_controller().freeze_status(shell)


def set_compute_diagnostics_freeze_armed(
    *,
    game_id: int,
    perspective: int,
    turn: int,
    freeze_armed: bool,
) -> None:
    """Arm or disarm freeze mode for the game of one shell context."""
    shell = _shell(game_id=game_id, perspective=perspective, turn=turn)
    get_compute_diagnostics_controller().set_freeze_armed(shell, freeze_armed=freeze_armed)


def set_compute_diagnostics_allowlist(
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_ids: frozenset[int],
) -> None:
    """Set the per-shell player allowlist while freeze mode is armed."""
    shell = _shell(game_id=game_id, perspective=perspective, turn=turn)
    get_compute_diagnostics_controller().set_allowlist(shell, player_ids)


def run_compute_diagnostics_single_step(
    *,
    game_id: int,
    perspective: int,
    turn: int,
) -> bool:
    """Release exactly one pool work item for the shell; return whether armed."""
    shell = _shell(game_id=game_id, perspective=perspective, turn=turn)
    return get_compute_diagnostics_controller().single_step(shell)


def get_compute_diagnostics_stream_allowlist(
    *,
    game_id: int,
    perspective: int,
    turn: int,
) -> frozenset[int] | None:
    """When freeze is armed, return allowlisted players for stream narrowing."""
    shell = _shell(game_id=game_id, perspective=perspective, turn=turn)
    return get_compute_diagnostics_controller().stream_allowlisted_player_ids(shell)
