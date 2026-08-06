"""Homeworld evidence strength class mapping and max-strength resolution (#37).

Kind → ``weak`` < ``strong`` < ``asserted``. Decision/display state uses only
provenances at the highest present class; same-strength conflicts stay unresolved.
``preferred_candidate_ownership`` is strong only when its planet is already
location-definite (caller supplies that context at resolve time).
``ship_travel_envelope`` is weak for Privateer owners (Rob + tow-capture can
place ships outside a true travel path from their homeworld).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from api.analytics.homeworld_locator.models import (
    EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD,
    PROVENANCE_ASSERTED,
    PROVENANCE_BASELINE_PROFILE,
    PROVENANCE_NEARBY_PLANET_OWNERSHIP,
    PROVENANCE_ORIGIN_DISTANCE,
    PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
    PROVENANCE_SHIP_TRAVEL_ENVELOPE,
    LocationProvenance,
    SectorOwnerMember,
)
from api.concepts.races import is_privateer

STRENGTH_WEAK = "weak"
STRENGTH_STRONG = "strong"
STRENGTH_ASSERTED = "asserted"

_STRENGTH_RANK: Mapping[str, int] = {
    STRENGTH_WEAK: 1,
    STRENGTH_STRONG: 2,
    STRENGTH_ASSERTED: 3,
}

_LOCATION_KIND_STRENGTH: Mapping[str, str] = {
    PROVENANCE_ORIGIN_DISTANCE: STRENGTH_WEAK,
    PROVENANCE_BASELINE_PROFILE: STRENGTH_STRONG,
    EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD: STRENGTH_STRONG,
    PROVENANCE_ASSERTED: STRENGTH_ASSERTED,
}

_OWNERSHIP_KIND_STRENGTH: Mapping[str, str] = {
    PROVENANCE_NEARBY_PLANET_OWNERSHIP: STRENGTH_WEAK,
    PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP: STRENGTH_WEAK,
    PROVENANCE_SHIP_TRAVEL_ENVELOPE: STRENGTH_STRONG,
    PROVENANCE_ASSERTED: STRENGTH_ASSERTED,
}


def location_provenance_strength(kind: str) -> str:
    """Map a location provenance kind to its homeworld evidence strength class."""
    strength = _LOCATION_KIND_STRENGTH.get(kind)
    if strength is None:
        raise ValueError(f"unknown homeworld location provenance kind: {kind!r}")
    return strength


def ownership_provenance_strength(
    kind: str,
    *,
    preferred_location_definite: bool = False,
    owner_race_id: int | None = None,
) -> str:
    """Map an ownership provenance kind to its homeworld evidence strength class.

    ``preferred_candidate_ownership`` upgrades to strong when the preferred
    candidate is already definite on the location axis.
    ``ship_travel_envelope`` stays strong for non-Privateer owners; Privateer
    owners (``owner_race_id``) demote to weak because Rob/tow-capture can put
    owned ships near foreign homeworlds without travel from the Privateer HW.
    Missing ``owner_race_id`` keeps the default strong mapping (``resolve_ownership_axis``
    looks up race from the required ``race_id_by_owner_slot`` map).
    """
    if kind == PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP and preferred_location_definite:
        return STRENGTH_STRONG
    if (
        kind == PROVENANCE_SHIP_TRAVEL_ENVELOPE
        and owner_race_id is not None
        and is_privateer(owner_race_id)
    ):
        return STRENGTH_WEAK
    strength = _OWNERSHIP_KIND_STRENGTH.get(kind)
    if strength is None:
        raise ValueError(f"unknown homeworld ownership provenance kind: {kind!r}")
    return strength


def _max_strength(strengths: Sequence[str]) -> str | None:
    if not strengths:
        return None
    return max(strengths, key=lambda item: _STRENGTH_RANK[item])


@dataclass(frozen=True)
class LocationAxisResolution:
    """Outcome of max-strength resolution on a location provenance list."""

    winning_strength: str | None
    resolved_planet_id: int | None
    contending_planet_ids: tuple[int, ...]
    is_definite: bool


@dataclass(frozen=True)
class OwnershipAxisResolution:
    """Outcome of max-strength resolution on a sector (or planet) owner set."""

    winning_strength: str | None
    resolved_owner_slot: int | None
    contending_owner_slots: tuple[int, ...]
    is_unique: bool


def resolve_location_axis(
    provenances: Sequence[LocationProvenance],
) -> LocationAxisResolution:
    """Resolve location from provenances: max strength wins; conflicts stay possible."""
    if not provenances:
        return LocationAxisResolution(
            winning_strength=None,
            resolved_planet_id=None,
            contending_planet_ids=(),
            is_definite=False,
        )
    by_planet_strength: dict[int, str] = {}
    for row in provenances:
        strength = location_provenance_strength(row.kind)
        prior = by_planet_strength.get(row.planet_id)
        if prior is None or _STRENGTH_RANK[strength] > _STRENGTH_RANK[prior]:
            by_planet_strength[row.planet_id] = strength
    winning = _max_strength(tuple(by_planet_strength.values()))
    assert winning is not None
    contenders = tuple(
        sorted(
            planet_id for planet_id, strength in by_planet_strength.items() if strength == winning
        )
    )
    is_definite = winning in (STRENGTH_STRONG, STRENGTH_ASSERTED) and len(contenders) == 1
    return LocationAxisResolution(
        winning_strength=winning,
        resolved_planet_id=contenders[0] if is_definite else None,
        contending_planet_ids=contenders,
        is_definite=is_definite,
    )


def _member_winning_strength(
    member: SectorOwnerMember,
    *,
    location_definite_planet_ids: frozenset[int],
    race_id_by_owner_slot: Mapping[int, int],
) -> str | None:
    strengths: list[str] = []
    owner_race_id = race_id_by_owner_slot.get(member.owner_slot)
    for provenance in member.provenances:
        preferred_definite = (
            provenance.kind == PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP
            and provenance.planet_id is not None
            and provenance.planet_id in location_definite_planet_ids
        )
        strengths.append(
            ownership_provenance_strength(
                provenance.kind,
                preferred_location_definite=preferred_definite,
                owner_race_id=owner_race_id,
            )
        )
    return _max_strength(strengths)


def resolve_ownership_axis(
    members: Sequence[SectorOwnerMember],
    *,
    race_id_by_owner_slot: Mapping[int, int],
    location_definite_planet_ids: frozenset[int] | None = None,
) -> OwnershipAxisResolution:
    """Resolve ownership from member provenances: max strength wins; ties stay ambiguous.

    ``race_id_by_owner_slot`` is required so race-sensitive kinds (Privateer
    ``ship_travel_envelope``) cannot silently stay strong via omitted race context.
    Empty maps are allowed when the caller has no roster (e.g. tests without
    race-sensitive members); unknown slots still resolve as non-Privateer.
    """
    definite_ids = location_definite_planet_ids or frozenset()
    if not members:
        return OwnershipAxisResolution(
            winning_strength=None,
            resolved_owner_slot=None,
            contending_owner_slots=(),
            is_unique=False,
        )
    by_slot_strength: dict[int, str] = {}
    for member in members:
        strength = _member_winning_strength(
            member,
            location_definite_planet_ids=definite_ids,
            race_id_by_owner_slot=race_id_by_owner_slot,
        )
        if strength is None:
            continue
        by_slot_strength[member.owner_slot] = strength
    if not by_slot_strength:
        return OwnershipAxisResolution(
            winning_strength=None,
            resolved_owner_slot=None,
            contending_owner_slots=(),
            is_unique=False,
        )
    winning = _max_strength(tuple(by_slot_strength.values()))
    assert winning is not None
    contenders = tuple(
        sorted(slot for slot, strength in by_slot_strength.items() if strength == winning)
    )
    is_unique = len(contenders) == 1
    return OwnershipAxisResolution(
        winning_strength=winning,
        resolved_owner_slot=contenders[0] if is_unique else None,
        contending_owner_slots=contenders,
        is_unique=is_unique,
    )


def location_has_asserted_strength(
    location_provenances: Sequence[LocationProvenance] = (),
) -> bool:
    """True when any location provenance has asserted strength."""
    return any(
        location_provenance_strength(row.kind) == STRENGTH_ASSERTED for row in location_provenances
    )


def provenance_has_asserted_strength(
    *,
    location_provenances: Sequence[LocationProvenance] = (),
    ownership_members: Sequence[SectorOwnerMember] = (),
) -> bool:
    """True when any provenance on either axis has asserted strength."""
    if location_has_asserted_strength(location_provenances):
        return True
    for member in ownership_members:
        for provenance in member.provenances:
            if ownership_provenance_strength(provenance.kind) == STRENGTH_ASSERTED:
                return True
    return False


__all__ = [
    "STRENGTH_ASSERTED",
    "STRENGTH_STRONG",
    "STRENGTH_WEAK",
    "LocationAxisResolution",
    "OwnershipAxisResolution",
    "location_has_asserted_strength",
    "location_provenance_strength",
    "ownership_provenance_strength",
    "provenance_has_asserted_strength",
    "resolve_location_axis",
    "resolve_ownership_axis",
]
