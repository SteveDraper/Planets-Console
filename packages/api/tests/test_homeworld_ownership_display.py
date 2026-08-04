"""Display-time projection of sector possible-owner sets."""

from __future__ import annotations

from api.analytics.homeworld_locator.models import (
    PROVENANCE_ASSERTED,
    PROVENANCE_NEARBY_PLANET_OWNERSHIP,
    PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
    PROVENANCE_SHIP_TRAVEL_ENVELOPE,
    OwnershipProvenance,
    SectorOwnerMember,
)
from api.analytics.homeworld_locator.ownership_display import (
    ownership_winning_strength_for_members,
    project_sector_owner_sets_for_display,
)


def _member(slot: int, *kinds: str, planet_id: int | None = None) -> SectorOwnerMember:
    provenances = tuple(
        OwnershipProvenance(
            kind=kind,
            turn=1,
            ship_id=10 if kind == PROVENANCE_SHIP_TRAVEL_ENVELOPE else None,
            planet_id=planet_id if kind != PROVENANCE_SHIP_TRAVEL_ENVELOPE else None,
        )
        for kind in kinds
    )
    return SectorOwnerMember(owner_slot=slot, provenances=provenances)


def test_strength_filter_drops_weaker_members() -> None:
    sets = {
        0: (
            _member(1, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
            _member(2, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=99),
        ),
    }
    projected = project_sector_owner_sets_for_display(sets)
    assert [m.owner_slot for m in projected[0]] == [1]


def test_cross_sector_trim_removes_settled_owner_elsewhere() -> None:
    sets = {
        0: (_member(3, PROVENANCE_SHIP_TRAVEL_ENVELOPE),),
        1: (
            _member(3, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=50),
            _member(5, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=51),
        ),
    }
    projected = project_sector_owner_sets_for_display(sets)
    assert [m.owner_slot for m in projected[0]] == [3]
    assert [m.owner_slot for m in projected[1]] == [5]


def test_location_pin_settles_owner_for_cross_sector_trim() -> None:
    sets = {
        0: (),
        1: (
            _member(2, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=50),
            _member(4, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=51),
        ),
    }
    projected = project_sector_owner_sets_for_display(
        sets,
        settled_owner_home_by_slot={2: 0},
    )
    assert projected[0] == ()
    assert [m.owner_slot for m in projected[1]] == [4]


def test_preferred_upgrades_when_planet_location_definite() -> None:
    sets = {
        0: (
            _member(3, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=42),
            _member(4, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=99),
        ),
    }
    projected = project_sector_owner_sets_for_display(
        sets,
        location_definite_planet_ids=frozenset({42}),
    )
    assert [m.owner_slot for m in projected[0]] == [3]


def test_asserted_settles_for_cross_sector_trim() -> None:
    sets = {
        0: (_member(1, PROVENANCE_ASSERTED),),
        1: (
            _member(1, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=9),
            _member(7, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=10),
        ),
    }
    projected = project_sector_owner_sets_for_display(sets)
    assert [m.owner_slot for m in projected[1]] == [7]


def test_winning_strength_emitted_only_when_unique() -> None:
    unique = (_member(1, PROVENANCE_SHIP_TRAVEL_ENVELOPE),)
    assert ownership_winning_strength_for_members(unique) == "strong"

    ambiguous_strong = (
        _member(2, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
        _member(5, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
    )
    assert ownership_winning_strength_for_members(ambiguous_strong) is None

    empty: tuple[SectorOwnerMember, ...] = ()
    assert ownership_winning_strength_for_members(empty) is None


def test_winning_strength_omitted_for_ambiguous_preferred_upgrade() -> None:
    """Location-definite preferred can be strong, but ties must not emit a sector max."""
    members = (
        _member(3, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=42),
        _member(4, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=43),
    )
    assert (
        ownership_winning_strength_for_members(
            members,
            location_definite_planet_ids=frozenset({42, 43}),
        )
        is None
    )
    unique = (_member(3, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=42),)
    assert (
        ownership_winning_strength_for_members(
            unique,
            location_definite_planet_ids=frozenset({42}),
        )
        == "strong"
    )
