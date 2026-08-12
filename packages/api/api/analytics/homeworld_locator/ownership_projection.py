"""Overlay-wire projection of sector possible-owner sets (ADR 0010).

Durable ownership evidence keeps full provenance membership. Overlay emission
derives winning-strength contenders and trims slots that are already uniquely
settled (strong or asserted) on exactly one other sector -- so assert changes
cannot leave sticky durable holes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from api.analytics.homeworld_locator.evidence_strength import (
    STRENGTH_ASSERTED,
    STRENGTH_STRONG,
    OwnershipAxisResolution,
    resolve_ownership_axis,
)
from api.analytics.homeworld_locator.models import SectorOwnerMember

_SETTLED_STRENGTHS = frozenset({STRENGTH_STRONG, STRENGTH_ASSERTED})


class SectorOwnerOverlayProjection(NamedTuple):
    members: tuple[SectorOwnerMember, ...]
    winning_strength: str | None


def settled_owner_homes_from_location_pins(
    candidate_planet_ids_by_sector: Sequence[Sequence[int]],
    *,
    location_definite_planet_ids: frozenset[int],
    perspective_by_planet_id: Mapping[int, int],
) -> dict[int, int]:
    """Map owner slots to a unique home sector from definite location pins.

    A slot settles only when every location-definite, perspective-anchored
    candidate for that slot falls in exactly one sector. Multi-sector claims
    leave the slot unsettled so cross-sector trim does not fire.
    """
    if not location_definite_planet_ids or not perspective_by_planet_id:
        return {}

    location_home_claims: dict[int, list[int]] = {}
    for sector_index, planet_ids in enumerate(candidate_planet_ids_by_sector):
        for planet_id in planet_ids:
            if planet_id not in location_definite_planet_ids:
                continue
            owner_slot = perspective_by_planet_id.get(planet_id)
            if owner_slot is None:
                continue
            location_home_claims.setdefault(owner_slot, []).append(sector_index)

    return {
        owner_slot: sectors[0]
        for owner_slot, sectors in location_home_claims.items()
        if len(set(sectors)) == 1
    }


def project_sector_owner_sets_for_overlays(
    sector_owner_sets: Mapping[int, Sequence[SectorOwnerMember]],
    *,
    race_id_by_owner_slot: Mapping[int, int],
    location_definite_planet_ids: frozenset[int] = frozenset(),
    settled_owner_home_by_slot: Mapping[int, int] | None = None,
) -> dict[int, SectorOwnerOverlayProjection]:
    """Project durable sector owner sets for overlay wire facts.

    1. Keep only max-strength contenders per sector (ADR 0010).
    2. When a slot is uniquely settled on exactly one sector -- via strong/asserted
       ownership resolution, and/or a caller-supplied location pin home
       (definite slot-anchored candidate) -- drop that slot from every other
       sector's projected set.

    Returns projected members plus ``winning_strength`` for unique sets
    (``None`` when ownership is ambiguous). Reuses the first-pass axis resolution
    when cross-sector trim does not change contender membership.
    ``race_id_by_owner_slot`` is required (empty map allowed when no race context).
    """
    if not sector_owner_sets:
        return {}

    strength_filtered: dict[int, tuple[SectorOwnerMember, ...]] = {}
    resolutions: dict[int, OwnershipAxisResolution] = {}
    for sector_index, members in sector_owner_sets.items():
        member_tuple = tuple(members)
        resolution = resolve_ownership_axis(
            member_tuple,
            race_id_by_owner_slot=race_id_by_owner_slot,
            location_definite_planet_ids=location_definite_planet_ids,
        )
        resolutions[sector_index] = resolution
        contenders = frozenset(resolution.contending_owner_slots)
        strength_filtered[sector_index] = tuple(
            member for member in member_tuple if member.owner_slot in contenders
        )

    slot_claims: dict[int, list[int]] = defaultdict(list)
    for sector_index, resolution in resolutions.items():
        if (
            resolution.is_unique
            and resolution.winning_strength in _SETTLED_STRENGTHS
            and resolution.resolved_owner_slot is not None
        ):
            slot_claims[resolution.resolved_owner_slot].append(sector_index)

    settled_home = {
        owner_slot: sectors[0] for owner_slot, sectors in slot_claims.items() if len(sectors) == 1
    }
    for owner_slot, home_sector in dict(settled_owner_home_by_slot or ()).items():
        prior = settled_home.get(owner_slot)
        if prior is None:
            settled_home[owner_slot] = home_sector
        elif prior != home_sector:
            # Conflicting homes -- do not settle this slot for cross-sector trim.
            del settled_home[owner_slot]

    if not settled_home:
        projected = strength_filtered
    else:
        projected = {
            sector_index: tuple(
                member
                for member in members
                if member.owner_slot not in settled_home
                or settled_home[member.owner_slot] == sector_index
            )
            for sector_index, members in strength_filtered.items()
        }

    return {
        sector_index: SectorOwnerOverlayProjection(
            members=members,
            winning_strength=_winning_strength_for_projected(
                members,
                location_definite_planet_ids=location_definite_planet_ids,
                race_id_by_owner_slot=race_id_by_owner_slot,
                prior_resolution=resolutions.get(sector_index),
            ),
        )
        for sector_index, members in projected.items()
    }


def _winning_strength_for_projected(
    members: tuple[SectorOwnerMember, ...],
    *,
    location_definite_planet_ids: frozenset[int],
    race_id_by_owner_slot: Mapping[int, int],
    prior_resolution: OwnershipAxisResolution | None,
) -> str | None:
    if not members:
        return None
    if prior_resolution is not None:
        prior_slots = frozenset(prior_resolution.contending_owner_slots)
        member_slots = frozenset(member.owner_slot for member in members)
        if member_slots == prior_slots:
            return prior_resolution.winning_strength if prior_resolution.is_unique else None
    return ownership_winning_strength_for_members(
        members,
        location_definite_planet_ids=location_definite_planet_ids,
        race_id_by_owner_slot=race_id_by_owner_slot,
    )


def ownership_winning_strength_for_members(
    members: Sequence[SectorOwnerMember],
    *,
    race_id_by_owner_slot: Mapping[int, int],
    location_definite_planet_ids: frozenset[int] = frozenset(),
) -> str | None:
    """Winning ownership strength for a unique projected owner set, else None.

    Sector ``ownershipWinningStrength`` is only meaningful when ``|set|=1``.
    Ambiguous ties keep contenders but omit the field so clients cannot apply a
    sector-wide max strength to every owner.
    ``race_id_by_owner_slot`` is required (empty map allowed when no race context).
    """
    if not members:
        return None
    resolution = resolve_ownership_axis(
        members,
        race_id_by_owner_slot=race_id_by_owner_slot,
        location_definite_planet_ids=location_definite_planet_ids,
    )
    if not resolution.is_unique:
        return None
    return resolution.winning_strength


def unique_projected_owner_slot(
    projection: SectorOwnerOverlayProjection,
) -> int | None:
    """Owner slot when the projected set has exactly one member, else None.

    This is the sole sector-pin test: overlay ``is_pinned``, unique-owner
    orphan bind, and display uniqueness all use this helper.
    """
    if len(projection.members) != 1:
        return None
    return projection.members[0].owner_slot


def project_sector_owner_sets_with_location_pins(
    sector_owner_sets: Mapping[int, Sequence[SectorOwnerMember]],
    *,
    candidate_planet_ids_by_sector: Sequence[Sequence[int]],
    location_definite_planet_ids: frozenset[int],
    perspective_by_planet_id: Mapping[int, int],
    race_id_by_owner_slot: Mapping[int, int],
) -> dict[int, SectorOwnerOverlayProjection]:
    """Project overlay owner sets, settling homes from definite location pins.

    Overlay emit and unique-owner orphan bind both use this so ``is_pinned``
    and orphan ``perspective`` share one uniqueness snapshot.
    """
    settled = settled_owner_homes_from_location_pins(
        candidate_planet_ids_by_sector,
        location_definite_planet_ids=location_definite_planet_ids,
        perspective_by_planet_id=perspective_by_planet_id,
    )
    return project_sector_owner_sets_for_overlays(
        sector_owner_sets,
        race_id_by_owner_slot=race_id_by_owner_slot,
        location_definite_planet_ids=location_definite_planet_ids,
        settled_owner_home_by_slot=settled,
    )


__all__ = [
    "SectorOwnerOverlayProjection",
    "ownership_winning_strength_for_members",
    "project_sector_owner_sets_for_overlays",
    "project_sector_owner_sets_with_location_pins",
    "settled_owner_homes_from_location_pins",
    "unique_projected_owner_slot",
]
