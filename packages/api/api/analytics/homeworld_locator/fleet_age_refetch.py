"""Durable fleet-age refetch notices for the homeworld locator.

Identity changes append a bounded ``(generation, turn)`` log on the homeworld
fleet-age document. The poll reads that log. ``from_turn`` is the earliest
turn changed after ``after_epoch``, null when that epoch is current, and 1
when ``after_epoch`` is ahead of the stored generation or the retained window
no longer holds the answer.

``fleet_age_identity_changed_handler`` is the production callback. It records
the durable stale marker and this log. It does not ensure homeworld or fleet.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.fleet.ledger_persisted_event import FleetAgeIdentityChanged

if TYPE_CHECKING:
    from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService

FLEET_AGE_RETAINED_CHANGES = 256


@dataclass(frozen=True)
class FleetAgeRefetchNotice:
    """Epoch of build-turn identity changes, and the earliest turn after ``after_epoch``."""

    epoch: int
    from_turn: int | None


def notice_for_fleet_age_changes(
    generation: int,
    changes: Sequence[tuple[int, int]],
    *,
    after_epoch: int,
) -> FleetAgeRefetchNotice:
    """Changes with a generation above ``after_epoch``.

    ``from_turn`` is 1 when ``after_epoch`` is ahead of ``generation`` (a client
    epoch this store does not have) or when the retained window does not hold
    every change after ``after_epoch``. Returning the stored generation lets
    the client resync instead of polling as if the epoch had not moved.
    """
    if after_epoch > generation:
        return FleetAgeRefetchNotice(epoch=generation, from_turn=1)
    if generation == after_epoch:
        return FleetAgeRefetchNotice(epoch=generation, from_turn=None)
    if not changes or changes[0][0] > after_epoch + 1:
        return FleetAgeRefetchNotice(epoch=generation, from_turn=1)
    turns = [turn for change_generation, turn in changes if change_generation > after_epoch]
    if not turns:
        return FleetAgeRefetchNotice(epoch=generation, from_turn=1)
    return FleetAgeRefetchNotice(epoch=generation, from_turn=min(turns))


def fleet_age_identity_changed_handler(
    homeworld_persistence: HomeworldLocatorPersistenceService,
) -> Callable[[FleetAgeIdentityChanged], None]:
    """Durable stale marker and refetch log for one homeworld store."""

    def on_changed(event: FleetAgeIdentityChanged) -> None:
        homeworld_persistence.record_fleet_age_identity_changed(event)

    return on_changed
