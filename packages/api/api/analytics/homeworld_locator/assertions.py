"""Game-global homeworld assertion upsert/revoke (domain only; no HTTP)."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.homeworld_locator.models import (
    PROVENANCE_ASSERTED,
    LocationProvenance,
    OwnershipProvenance,
    SectorOwnerMember,
)
from api.analytics.homeworld_locator.ownership_evidence import add_provenance_to_sector_owner_set
from api.analytics.homeworld_locator.types import (
    HomeworldLocatorGameState,
    ensure_candidates_for_asserted_locations,
)


def _asserted_ownership_provenance(*, turn: int) -> OwnershipProvenance:
    return OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=turn)


def _put_owner_set_row(
    rows: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...],
    *,
    key: int,
    owner_slot: int,
    turn: int,
) -> tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]:
    by_key = dict(rows)
    prior = by_key.get(key, ())
    # Upsert: replace any prior asserted provenance for this slot on this key.
    without_slot = tuple(member for member in prior if member.owner_slot != owner_slot)
    by_key[key] = add_provenance_to_sector_owner_set(
        without_slot,
        owner_slot=owner_slot,
        provenance=_asserted_ownership_provenance(turn=turn),
    )
    return tuple(sorted(by_key.items(), key=lambda item: item[0]))


def _drop_owner_set_slot(
    rows: tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...],
    *,
    key: int,
    owner_slot: int,
) -> tuple[tuple[int, tuple[SectorOwnerMember, ...]], ...]:
    by_key = dict(rows)
    prior = by_key.get(key)
    if prior is None:
        return rows
    remaining = tuple(member for member in prior if member.owner_slot != owner_slot)
    if remaining:
        by_key[key] = remaining
    else:
        del by_key[key]
    return tuple(sorted(by_key.items(), key=lambda item: item[0]))


def upsert_location_assertion(
    state: HomeworldLocatorGameState,
    *,
    planet_id: int,
    turn: int,
) -> HomeworldLocatorGameState:
    """Add or replace a positive location assert for ``planet_id``; ensure a candidate exists."""
    if planet_id < 1:
        raise ValueError("planet_id must be >= 1")
    if turn < 1:
        raise ValueError("turn must be >= 1")
    remaining = tuple(
        row for row in state.asserted_location_provenances if row.planet_id != planet_id
    )
    asserted = (
        *remaining,
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=turn, planet_id=planet_id),
    )
    candidates = ensure_candidates_for_asserted_locations(
        inferred=state.candidates,
        asserted_location_provenances=asserted,
    )
    return replace(
        state,
        candidates=candidates,
        asserted_location_provenances=asserted,
    )


def revoke_location_assertion(
    state: HomeworldLocatorGameState,
    *,
    planet_id: int,
) -> HomeworldLocatorGameState:
    """Remove the asserted location provenance for ``planet_id`` (machine facts untouched)."""
    asserted = tuple(
        row for row in state.asserted_location_provenances if row.planet_id != planet_id
    )
    return replace(state, asserted_location_provenances=asserted)


def upsert_ownership_assertion(
    state: HomeworldLocatorGameState,
    *,
    owner_slot: int,
    turn: int,
    sector_index: int | None,
    planet_id: int | None,
    sectors_exist: bool,
) -> HomeworldLocatorGameState:
    """Add or replace an ownership assert; sector-keyed xor planet-keyed per geometry."""
    if owner_slot < 1:
        raise ValueError("owner_slot must be >= 1")
    if turn < 1:
        raise ValueError("turn must be >= 1")
    if sectors_exist:
        if sector_index is None:
            raise ValueError("ownership assert requires sector_index when sectors exist")
        if sector_index < 0:
            raise ValueError("sector_index must be >= 0")
        return replace(
            state,
            asserted_sector_ownership=_put_owner_set_row(
                state.asserted_sector_ownership,
                key=sector_index,
                owner_slot=owner_slot,
                turn=turn,
            ),
            # Do not dual-persist planet-keyed when sectors exist.
            asserted_planet_ownership=(),
        )
    if planet_id is None:
        raise ValueError("ownership assert requires planet_id when sectors do not exist")
    if planet_id < 1:
        raise ValueError("planet_id must be >= 1")
    return replace(
        state,
        asserted_planet_ownership=_put_owner_set_row(
            state.asserted_planet_ownership,
            key=planet_id,
            owner_slot=owner_slot,
            turn=turn,
        ),
        asserted_sector_ownership=(),
    )


def revoke_ownership_assertion(
    state: HomeworldLocatorGameState,
    *,
    owner_slot: int,
    sector_index: int | None,
    planet_id: int | None,
    sectors_exist: bool,
) -> HomeworldLocatorGameState:
    """Remove an asserted ownership provenance for the keyed target."""
    if owner_slot < 1:
        raise ValueError("owner_slot must be >= 1")
    if sectors_exist:
        if sector_index is None:
            raise ValueError("ownership revoke requires sector_index when sectors exist")
        return replace(
            state,
            asserted_sector_ownership=_drop_owner_set_slot(
                state.asserted_sector_ownership,
                key=sector_index,
                owner_slot=owner_slot,
            ),
        )
    if planet_id is None:
        raise ValueError("ownership revoke requires planet_id when sectors do not exist")
    return replace(
        state,
        asserted_planet_ownership=_drop_owner_set_slot(
            state.asserted_planet_ownership,
            key=planet_id,
            owner_slot=owner_slot,
        ),
    )


__all__ = [
    "revoke_location_assertion",
    "revoke_ownership_assertion",
    "upsert_location_assertion",
    "upsert_ownership_assertion",
]
