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
from api.analytics.homeworld_locator.ownership_projection import (
    ownership_winning_strength_for_members,
    project_sector_owner_sets_for_overlays,
    settled_owner_homes_from_location_pins,
    unique_projected_owner_slot,
)
from api.concepts.races import PRIVATEER_RACE_ID


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
    projected = project_sector_owner_sets_for_overlays(sets, race_id_by_owner_slot={})
    assert [m.owner_slot for m in projected[0].members] == [1]


def test_privateer_envelope_does_not_outrank_nearby_planet_ownership() -> None:
    """Privateer Rob/tow-capture makes ship envelopes weak -- stay ambiguous with nearby."""
    sets = {
        0: (
            _member(5, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
            _member(2, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=45),
        ),
    }
    projected = project_sector_owner_sets_for_overlays(
        sets,
        race_id_by_owner_slot={5: PRIVATEER_RACE_ID, 2: 2},
    )
    assert [m.owner_slot for m in projected[0].members] == [5, 2]
    assert projected[0].winning_strength is None

    alone = project_sector_owner_sets_for_overlays(
        {0: (_member(5, PROVENANCE_SHIP_TRAVEL_ENVELOPE),)},
        race_id_by_owner_slot={5: PRIVATEER_RACE_ID},
    )
    assert [m.owner_slot for m in alone[0].members] == [5]
    assert alone[0].winning_strength == "weak"


def test_cross_sector_trim_removes_settled_owner_elsewhere() -> None:
    sets = {
        0: (_member(3, PROVENANCE_SHIP_TRAVEL_ENVELOPE),),
        1: (
            _member(3, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=50),
            _member(5, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=51),
        ),
    }
    projected = project_sector_owner_sets_for_overlays(sets, race_id_by_owner_slot={})
    assert [m.owner_slot for m in projected[0].members] == [3]
    assert [m.owner_slot for m in projected[1].members] == [5]


def test_location_pin_settles_owner_for_cross_sector_trim() -> None:
    sets = {
        0: (),
        1: (
            _member(2, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=50),
            _member(4, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=51),
        ),
    }
    projected = project_sector_owner_sets_for_overlays(
        sets,
        race_id_by_owner_slot={},
        settled_owner_home_by_slot={2: 0},
    )
    assert projected[0].members == ()
    assert [m.owner_slot for m in projected[1].members] == [4]


def test_settled_owner_homes_from_location_pins_unique_sector() -> None:
    settled = settled_owner_homes_from_location_pins(
        [[10, 11], [20], [30]],
        location_definite_planet_ids=frozenset({20}),
        perspective_by_planet_id={20: 2},
    )
    assert settled == {2: 1}


def test_settled_owner_homes_from_location_pins_multi_sector_unsettled() -> None:
    settled = settled_owner_homes_from_location_pins(
        [[10], [20], []],
        location_definite_planet_ids=frozenset({10, 20}),
        perspective_by_planet_id={10: 2, 20: 2},
    )
    assert settled == {}


def test_settled_owner_homes_from_location_pins_skips_missing_perspective() -> None:
    settled = settled_owner_homes_from_location_pins(
        [[10], [20]],
        location_definite_planet_ids=frozenset({10, 20}),
        perspective_by_planet_id={20: 3},
    )
    assert settled == {3: 1}


def test_settled_owner_homes_from_location_pins_duplicate_same_sector() -> None:
    settled = settled_owner_homes_from_location_pins(
        [[10, 11], []],
        location_definite_planet_ids=frozenset({10, 11}),
        perspective_by_planet_id={10: 4, 11: 4},
    )
    assert settled == {4: 0}


def test_preferred_upgrades_when_planet_location_definite() -> None:
    sets = {
        0: (
            _member(3, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=42),
            _member(4, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=99),
        ),
    }
    projected = project_sector_owner_sets_for_overlays(
        sets,
        race_id_by_owner_slot={},
        location_definite_planet_ids=frozenset({42}),
    )
    assert [m.owner_slot for m in projected[0].members] == [3]


def test_asserted_settles_for_cross_sector_trim() -> None:
    sets = {
        0: (_member(1, PROVENANCE_ASSERTED),),
        1: (
            _member(1, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=9),
            _member(7, PROVENANCE_NEARBY_PLANET_OWNERSHIP, planet_id=10),
        ),
    }
    projected = project_sector_owner_sets_for_overlays(sets, race_id_by_owner_slot={})
    assert [m.owner_slot for m in projected[1].members] == [7]


def test_winning_strength_emitted_only_when_unique() -> None:
    unique = (_member(1, PROVENANCE_SHIP_TRAVEL_ENVELOPE),)
    projected = project_sector_owner_sets_for_overlays({0: unique}, race_id_by_owner_slot={})
    assert projected[0].winning_strength == "strong"

    ambiguous_strong = (
        _member(2, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
        _member(5, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
    )
    projected = project_sector_owner_sets_for_overlays(
        {0: ambiguous_strong}, race_id_by_owner_slot={}
    )
    assert projected[0].winning_strength is None

    projected = project_sector_owner_sets_for_overlays({0: ()}, race_id_by_owner_slot={})
    assert projected[0].winning_strength is None

    assert ownership_winning_strength_for_members(unique, race_id_by_owner_slot={}) == "strong"
    assert (
        ownership_winning_strength_for_members(ambiguous_strong, race_id_by_owner_slot={}) is None
    )
    empty: tuple[SectorOwnerMember, ...] = ()
    assert ownership_winning_strength_for_members(empty, race_id_by_owner_slot={}) is None


def test_winning_strength_omitted_for_ambiguous_preferred_upgrade() -> None:
    """Location-definite preferred can be strong, but ties must not emit a sector max."""
    members = (
        _member(3, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=42),
        _member(4, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=43),
    )
    projected = project_sector_owner_sets_for_overlays(
        {0: members},
        race_id_by_owner_slot={},
        location_definite_planet_ids=frozenset({42, 43}),
    )
    assert projected[0].winning_strength is None
    unique = (_member(3, PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP, planet_id=42),)
    projected = project_sector_owner_sets_for_overlays(
        {0: unique},
        race_id_by_owner_slot={},
        location_definite_planet_ids=frozenset({42}),
    )
    assert projected[0].winning_strength == "strong"
    assert (
        ownership_winning_strength_for_members(
            members,
            race_id_by_owner_slot={},
            location_definite_planet_ids=frozenset({42, 43}),
        )
        is None
    )
    assert (
        ownership_winning_strength_for_members(
            unique,
            race_id_by_owner_slot={},
            location_definite_planet_ids=frozenset({42}),
        )
        == "strong"
    )


def test_unique_projected_owner_slot_is_exactly_one_member() -> None:
    unique = project_sector_owner_sets_for_overlays(
        {0: (_member(4, PROVENANCE_SHIP_TRAVEL_ENVELOPE),)},
        race_id_by_owner_slot={},
    )
    assert unique_projected_owner_slot(unique[0]) == 4

    ambiguous = project_sector_owner_sets_for_overlays(
        {
            0: (
                _member(2, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
                _member(6, PROVENANCE_SHIP_TRAVEL_ENVELOPE),
            )
        },
        race_id_by_owner_slot={},
    )
    assert unique_projected_owner_slot(ambiguous[0]) is None
