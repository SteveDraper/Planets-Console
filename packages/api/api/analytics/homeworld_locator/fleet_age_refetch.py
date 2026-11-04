"""In-process notice that a fleet build-turn identity changed.

The homeworld map query refetches a shown shell at or after the changed turn.
Turns after that shell are not ensured until they are shown. The notice does
not submit fleet work and does not delete evidence aggregates.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from api.analytics.fleet.ledger_persisted_event import FleetAgeIdentityChanged

_RETAINED_CHANGES = 256
_lock = threading.Lock()
_epochs: dict[tuple[int, int], int] = {}
_changes: dict[tuple[int, int], list[tuple[int, int]]] = {}


@dataclass(frozen=True)
class FleetAgeRefetchNotice:
    """Epoch of build-turn identity changes, and the earliest turn after ``after_epoch``."""

    epoch: int
    from_turn: int | None


def note_fleet_age_identity_changed(event: FleetAgeIdentityChanged) -> None:
    """Record one identity change. Does not ensure homeworld or fleet."""
    key = (event.game_id, event.perspective)
    with _lock:
        epoch = _epochs.get(key, 0) + 1
        _epochs[key] = epoch
        retained = _changes.setdefault(key, [])
        retained.append((epoch, event.turn))
        if len(retained) > _RETAINED_CHANGES:
            del retained[: len(retained) - _RETAINED_CHANGES]


def fleet_age_refetch_notice(
    game_id: int,
    perspective: int,
    *,
    after_epoch: int,
) -> FleetAgeRefetchNotice:
    """Changes with an epoch above ``after_epoch``.

    When the retained window no longer holds those changes, ``from_turn`` is 1
    so a shown shell still refetches.
    """
    key = (game_id, perspective)
    with _lock:
        epoch = _epochs.get(key, 0)
        if epoch <= after_epoch:
            return FleetAgeRefetchNotice(epoch=epoch, from_turn=None)
        retained = _changes.get(key, [])
        if not retained or retained[0][0] > after_epoch + 1:
            # Changes older than the retained window may include an earlier turn.
            return FleetAgeRefetchNotice(epoch=epoch, from_turn=1)
        turns = [turn for change_epoch, turn in retained if change_epoch > after_epoch]
        if not turns:
            return FleetAgeRefetchNotice(epoch=epoch, from_turn=1)
        return FleetAgeRefetchNotice(epoch=epoch, from_turn=min(turns))


def clear_fleet_age_refetch_notices() -> None:
    """Drop process-local notices. Tests only."""
    with _lock:
        _epochs.clear()
        _changes.clear()
