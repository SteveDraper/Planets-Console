"""Deferred fleet snapshot notifications after coordinated gap-fill completes."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.fleet.chain import _is_fleet_snapshot_cache_hit
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo


def complete_snapshot_turn_numbers(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    through_turn: int,
    load_turn: Callable[[int], TurnInfo | None],
) -> frozenset[int]:
    """Return fleet turn numbers through ``through_turn`` with ensure-final snapshots."""
    complete: set[int] = set()
    for turn_number in range(1, through_turn + 1):
        turn_info = load_turn(turn_number)
        if turn_info is None:
            continue
        snapshot = persistence.get_snapshot(game_id, perspective, turn_number)
        if _is_fleet_snapshot_cache_hit(
            persistence,
            game_id,
            perspective,
            turn_number,
            turn_info,
            snapshot,
        ):
            complete.add(turn_number)
    return frozenset(complete)


def emit_deferred_fleet_snapshot_notifications(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    *,
    complete_before: frozenset[int],
    through_turn: int,
    load_turn: Callable[[int], TurnInfo | None],
) -> None:
    """Notify scores consumers after coordinated gap-fill completes."""
    if persistence.on_snapshot_persisted is None:
        return
    complete_after = complete_snapshot_turn_numbers(
        persistence,
        game_id,
        perspective,
        through_turn,
        load_turn,
    )
    for fleet_turn in sorted(complete_after - complete_before):
        persistence.on_snapshot_persisted(game_id, perspective, fleet_turn)
