"""Build-turn identity changes for fleet ledger writes and removals."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.fleet.field_constraints import known_ship_built_turns
from api.analytics.fleet.ledger_persisted_event import FleetAgeIdentityChanged
from api.analytics.fleet.types import PersistedFleetLedger

OnFleetAgeIdentityChangedCallback = Callable[[FleetAgeIdentityChanged], None]


def _built_turn_identity(persisted: PersistedFleetLedger | None) -> dict[int, int] | None:
    """Known ship_id -> built_turn map, or None when the ledger file is absent."""
    if persisted is None:
        return None
    return known_ship_built_turns(persisted.ledger.records)


def notify_fleet_age_identity_if_changed(
    callback: OnFleetAgeIdentityChangedCallback | None,
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
    prior: PersistedFleetLedger | None,
    current: PersistedFleetLedger | None,
) -> None:
    """Invoke ``callback`` when the build-turn maps differ.

    A missing file is distinct from a ledger whose known built turns are empty.
    Other ledger field edits do not notify.
    """
    if callback is None or _built_turn_identity(prior) == _built_turn_identity(current):
        return
    _notify_fleet_age_identity_changed(
        callback,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        player_id=player_id,
    )


def notify_fleet_age_identity_removed(
    callback: OnFleetAgeIdentityChangedCallback | None,
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
) -> None:
    """Invoke ``callback`` because an on-disk ledger file was removed.

    The file is not read. A file that was present is an identity change.
    """
    _notify_fleet_age_identity_changed(
        callback,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        player_id=player_id,
    )


def _notify_fleet_age_identity_changed(
    callback: OnFleetAgeIdentityChangedCallback | None,
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
) -> None:
    """Deliver the event. No callback means no notification."""
    if callback is None:
        return
    callback(
        FleetAgeIdentityChanged(
            game_id=game_id,
            perspective=perspective,
            turn=turn,
            player_id=player_id,
        )
    )
