"""Build-turn identity diff for fleet ledger writes."""

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
    """Notify when the on-disk ship_id -> built_turn map is created, removed, or edited.

    A missing file is distinct from a ledger whose known built turns are empty.
    Other ledger field edits do not notify. This is not the ensure-final side channel.
    """
    if _built_turn_identity(prior) == _built_turn_identity(current):
        return
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
