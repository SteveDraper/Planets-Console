"""Deferred fleet ledger notifications after coordinated gap-fill completes."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.models.game import TurnInfo


def complete_ledger_turn_numbers_for_player(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    through_turn: int,
    load_turn: Callable[[int], TurnInfo | None],
) -> frozenset[int]:
    """Return turns through ``through_turn`` with ensure-final ledgers for one player."""
    complete: set[int] = set()
    for turn_number in range(1, through_turn + 1):
        turn_info = load_turn(turn_number)
        if turn_info is None:
            continue
        if persistence.has_final_ledger(game_id, perspective, turn_number, player_id):
            complete.add(turn_number)
    return frozenset(complete)


def emit_deferred_fleet_ledger_notifications(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
    *,
    complete_before: frozenset[int],
    through_turn: int,
    load_turn: Callable[[int], TurnInfo | None],
) -> None:
    """Notify scores consumers after coordinated gap-fill completes for one player."""
    if persistence.on_ledger_persisted is None:
        return
    complete_after = complete_ledger_turn_numbers_for_player(
        persistence,
        game_id,
        perspective,
        player_id,
        through_turn,
        load_turn,
    )
    for fleet_turn in sorted(complete_after - complete_before):
        persisted = persistence.get_ledger(game_id, perspective, fleet_turn, player_id)
        if persisted is None:
            continue
        persistence.on_ledger_persisted(
            FleetLedgerPersistedEvent(
                game_id=game_id,
                perspective=perspective,
                fleet_turn=fleet_turn,
                player_id=player_id,
                materialization_version=persisted.materialization_version,
            )
        )
