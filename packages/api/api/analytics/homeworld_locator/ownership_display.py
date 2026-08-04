"""Display-time projection of sector possible-owner sets (ADR 0010).

Durable ownership evidence keeps full provenance membership. Overlay / panel
display derives winning-strength contenders and trims slots that are already
uniquely settled (strong or asserted) on exactly one other sector -- so assert
changes cannot leave sticky durable holes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from api.analytics.homeworld_locator.evidence_strength import (
    STRENGTH_ASSERTED,
    STRENGTH_STRONG,
    resolve_ownership_axis,
)
from api.analytics.homeworld_locator.models import SectorOwnerMember

_SETTLED_STRENGTHS = frozenset({STRENGTH_STRONG, STRENGTH_ASSERTED})


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


def project_sector_owner_sets_for_display(
    sector_owner_sets: Mapping[int, Sequence[SectorOwnerMember]],
    *,
    location_definite_planet_ids: frozenset[int] = frozenset(),
    settled_owner_home_by_slot: Mapping[int, int] | None = None,
) -> dict[int, tuple[SectorOwnerMember, ...]]:
    """Project durable sector owner sets for wire / hover / title.

    1. Keep only max-strength contenders per sector (ADR 0010).
    2. When a slot is uniquely settled on exactly one sector -- via strong/asserted
       ownership resolution, and/or a caller-supplied location pin home
       (definite slot-anchored candidate) -- drop that slot from every other
       sector's projected set.
    """
    if not sector_owner_sets:
        return {}

    strength_filtered: dict[int, tuple[SectorOwnerMember, ...]] = {}
    resolutions = {}
    for sector_index, members in sector_owner_sets.items():
        member_tuple = tuple(members)
        resolution = resolve_ownership_axis(
            member_tuple,
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
        return strength_filtered

    projected: dict[int, tuple[SectorOwnerMember, ...]] = {}
    for sector_index, members in strength_filtered.items():
        projected[sector_index] = tuple(
            member
            for member in members
            if member.owner_slot not in settled_home
            or settled_home[member.owner_slot] == sector_index
        )
    return projected


def ownership_winning_strength_for_members(
    members: Sequence[SectorOwnerMember],
    *,
    location_definite_planet_ids: frozenset[int] = frozenset(),
) -> str | None:
    """Winning ownership strength for a unique projected owner set, else None.

    Sector ``ownershipWinningStrength`` is only meaningful when ``|set|=1``.
    Ambiguous ties keep contenders but omit the field so clients cannot apply a
    sector-wide max strength to every owner.
    """
    if not members:
        return None
    resolution = resolve_ownership_axis(
        members,
        location_definite_planet_ids=location_definite_planet_ids,
    )
    if not resolution.is_unique:
        return None
    return resolution.winning_strength


__all__ = [
    "ownership_winning_strength_for_members",
    "project_sector_owner_sets_for_display",
    "settled_owner_homes_from_location_pins",
]
