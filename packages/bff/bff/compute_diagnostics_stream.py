"""Shared helpers for compute-diagnostics stream narrowing."""

from __future__ import annotations

from api.services.compute_diagnostics_service import (
    compute_diagnostics_enabled,
    get_compute_diagnostics_stream_allowlist,
)


def filter_table_stream_player_ids(
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_ids: tuple[int, ...],
) -> tuple[int, ...]:
    """When freeze is armed, narrow stream subscriptions to allowlisted players."""
    if not compute_diagnostics_enabled():
        return player_ids
    allowlisted = get_compute_diagnostics_stream_allowlist(
        game_id=game_id,
        perspective=perspective,
        turn=turn,
    )
    if allowlisted is None:
        return player_ids
    return tuple(player_id for player_id in player_ids if player_id in allowlisted)
