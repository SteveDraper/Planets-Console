"""Homeworld evidence strength mapping and resolution (#37 Phase 1)."""

from __future__ import annotations

from api.analytics.homeworld_locator.evidence_strength import (
    STRENGTH_ASSERTED,
    STRENGTH_STRONG,
    STRENGTH_WEAK,
    location_has_asserted_strength,
    location_provenance_strength,
    ownership_provenance_strength,
    resolve_location_axis,
    resolve_ownership_axis,
)
from api.analytics.homeworld_locator.models import (
    EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD,
    PROVENANCE_ASSERTED,
    PROVENANCE_BASELINE_PROFILE,
    PROVENANCE_NEARBY_PLANET_OWNERSHIP,
    PROVENANCE_ORIGIN_DISTANCE,
    PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
    PROVENANCE_SHIP_TRAVEL_ENVELOPE,
    LocationProvenance,
    OwnershipProvenance,
    SectorOwnerMember,
)


def test_location_kind_strength_mapping() -> None:
    assert location_provenance_strength(PROVENANCE_ORIGIN_DISTANCE) == STRENGTH_WEAK
    assert location_provenance_strength(PROVENANCE_BASELINE_PROFILE) == STRENGTH_STRONG
    assert location_provenance_strength(EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD) == STRENGTH_STRONG
    assert location_provenance_strength(PROVENANCE_ASSERTED) == STRENGTH_ASSERTED


def test_location_has_asserted_strength_ignores_machine_kinds() -> None:
    machine_only = (
        LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
    )
    with_assert = (
        *machine_only,
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=10),
    )
    assert location_has_asserted_strength(machine_only) is False
    assert location_has_asserted_strength(with_assert) is True
    assert location_has_asserted_strength(()) is False


def test_ownership_kind_strength_mapping() -> None:
    assert ownership_provenance_strength(PROVENANCE_NEARBY_PLANET_OWNERSHIP) == STRENGTH_WEAK
    assert (
        ownership_provenance_strength(
            PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
            preferred_location_definite=False,
        )
        == STRENGTH_WEAK
    )
    assert (
        ownership_provenance_strength(
            PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
            preferred_location_definite=True,
        )
        == STRENGTH_STRONG
    )
    assert ownership_provenance_strength(PROVENANCE_SHIP_TRAVEL_ENVELOPE) == STRENGTH_STRONG
    assert ownership_provenance_strength(PROVENANCE_ASSERTED) == STRENGTH_ASSERTED


def test_resolve_location_asserted_wins_over_strong() -> None:
    provenances = (
        LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=20),
    )
    resolved = resolve_location_axis(provenances)
    assert resolved.winning_strength == STRENGTH_ASSERTED
    assert resolved.resolved_planet_id == 20
    assert resolved.is_definite is True


def test_resolve_location_same_strength_conflict_stays_possible() -> None:
    provenances = (
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=10),
        LocationProvenance(kind=PROVENANCE_ASSERTED, turn=6, planet_id=20),
    )
    resolved = resolve_location_axis(provenances)
    assert resolved.winning_strength == STRENGTH_ASSERTED
    assert resolved.resolved_planet_id is None
    assert resolved.is_definite is False
    assert resolved.contending_planet_ids == (10, 20)


def test_resolve_location_weak_only_is_possible() -> None:
    provenances = (LocationProvenance(kind=PROVENANCE_ORIGIN_DISTANCE, turn=3, planet_id=10),)
    resolved = resolve_location_axis(provenances)
    assert resolved.winning_strength == STRENGTH_WEAK
    assert resolved.is_definite is False
    assert resolved.resolved_planet_id is None


def test_resolve_ownership_asserted_wins_over_strong() -> None:
    members = (
        SectorOwnerMember(
            owner_slot=1,
            provenances=(
                OwnershipProvenance(kind=PROVENANCE_SHIP_TRAVEL_ENVELOPE, turn=4, ship_id=9),
            ),
        ),
        SectorOwnerMember(
            owner_slot=2,
            provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=5),),
        ),
    )
    resolved = resolve_ownership_axis(members)
    assert resolved.winning_strength == STRENGTH_ASSERTED
    assert resolved.resolved_owner_slot == 2
    assert resolved.is_unique is True


def test_resolve_ownership_same_strength_conflict_stays_ambiguous() -> None:
    members = (
        SectorOwnerMember(
            owner_slot=1,
            provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=5),),
        ),
        SectorOwnerMember(
            owner_slot=2,
            provenances=(OwnershipProvenance(kind=PROVENANCE_ASSERTED, turn=6),),
        ),
    )
    resolved = resolve_ownership_axis(members)
    assert resolved.winning_strength == STRENGTH_ASSERTED
    assert resolved.resolved_owner_slot is None
    assert resolved.is_unique is False
    assert resolved.contending_owner_slots == (1, 2)


def test_resolve_ownership_preferred_strong_when_planet_location_definite() -> None:
    members = (
        SectorOwnerMember(
            owner_slot=3,
            provenances=(
                OwnershipProvenance(
                    kind=PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
                    turn=2,
                    planet_id=42,
                ),
            ),
        ),
        SectorOwnerMember(
            owner_slot=4,
            provenances=(
                OwnershipProvenance(
                    kind=PROVENANCE_NEARBY_PLANET_OWNERSHIP,
                    turn=2,
                    planet_id=99,
                    distance_ly=50.0,
                ),
            ),
        ),
    )
    weak = resolve_ownership_axis(members, location_definite_planet_ids=frozenset())
    assert weak.winning_strength == STRENGTH_WEAK
    assert weak.contending_owner_slots == (3, 4)

    strong = resolve_ownership_axis(members, location_definite_planet_ids=frozenset({42}))
    assert strong.winning_strength == STRENGTH_STRONG
    assert strong.resolved_owner_slot == 3
    assert strong.is_unique is True
