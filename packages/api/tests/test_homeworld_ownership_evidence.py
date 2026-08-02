"""Unit tests for homeworld ownership evidence domain (#269 Phase 1)."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.constants import HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
from api.analytics.homeworld_locator.models import (
    AGE_SOURCE_FLEET_BUILT_TURN,
    AGE_SOURCE_SHIP_ID_SCOREBOARD,
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    PROVENANCE_NEARBY_PLANET_OWNERSHIP,
    PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
    PROVENANCE_SHIP_TRAVEL_ENVELOPE,
)
from api.analytics.homeworld_locator.ownership_evidence import (
    ENVELOPE_ROUNDING_SLACK_LY_PER_TURN,
    NEARBY_OWNERSHIP_RADIUS_LY,
    add_provenance_to_sector_owner_set,
    apply_nearby_planet_ownership,
    apply_preferred_candidate_ownership,
    apply_unique_sector_envelope_pin,
    earliest_built_turn_from_ship_id,
    engine_warp_capability,
    intersect_owner_possible_sectors,
    preferred_candidate_in_sector,
    reachable_sector_indexes,
    resolve_ship_built_turn,
    travel_envelope_radius_ly,
    travel_turns_at_shell,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.concepts.homeworld_layout import HW_DISTRIBUTION_CIRCULAR, MAP_SHAPE_ROUND
from api.concepts.hull_abilities import hull_has_hyperjump
from api.concepts.planet_connections.wells import max_travel_distance
from api.models.components import Engine, Hull
from api.models.planet import Planet
from api.models.ship import Ship
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _load_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


@pytest.fixture
def template_planet():
    return _load_turn().planets[0]


def _eligible_geometry_turn(template_planet, *, planets: list[Planet], ships: list | None = None):
    turn = _load_turn()
    players = [replace(turn.player, id=index + 1, username=f"p{index + 1}") for index in range(11)]
    settings = replace(
        turn.settings,
        turn=10,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        shiplimit=500,
        endturn=100,
        campaignmode=False,
    )
    return replace(
        turn,
        settings=settings,
        player=players[0],
        players=players,
        planets=planets,
        ships=ships or [],
    )


def _planet(
    template: Planet,
    *,
    planet_id: int,
    x: int,
    y: int,
    ownerid: int = 0,
    debrisdisk: int = 0,
) -> Planet:
    return replace(
        template,
        id=planet_id,
        name=f"P{planet_id}",
        x=x,
        y=y,
        ownerid=ownerid,
        debrisdisk=debrisdisk,
    )


def _ship(
    template: Ship,
    *,
    ship_id: int,
    x: int,
    y: int,
    ownerid: int = 2,
    hullid: int | None = None,
    engineid: int | None = None,
) -> Ship:
    return replace(
        template,
        id=ship_id,
        x=x,
        y=y,
        ownerid=ownerid,
        hullid=template.hullid if hullid is None else hullid,
        engineid=template.engineid if engineid is None else engineid,
    )


def _hull(*, hull_id: int, special: str = "") -> Hull:
    return Hull(
        id=hull_id,
        name=f"Hull{hull_id}",
        tritanium=0,
        duranium=0,
        molybdenum=0,
        fueltank=0,
        crew=0,
        engines=1,
        mass=0,
        techlevel=1,
        cargo=0,
        fighterbays=0,
        launchers=0,
        beams=0,
        cancloak=False,
        cost=0,
        special=special,
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def _engine(*, engine_id: int, techlevel: int) -> Engine:
    return Engine(
        id=engine_id,
        name=f"E{engine_id}",
        cost=0,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        techlevel=techlevel,
        warp1=0,
        warp2=0,
        warp3=0,
        warp4=0,
        warp5=0,
        warp6=0,
        warp7=0,
        warp8=0,
        warp9=0,
    )


def _candidate(
    planet_id: int,
    *,
    confidence_tier: str = CONFIDENCE_POSSIBLE,
) -> HomeworldCandidateRecord:
    return HomeworldCandidateRecord(
        planet_id=planet_id,
        perspective=None,
        confidence_tier=confidence_tier,
    )


def test_earliest_built_turn_from_ship_id_is_first_turn_total_covers_id() -> None:
    # Independent worked example: id 50 first covered when total hits 50 on turn 3.
    totals = {1: 20, 2: 40, 3: 55, 4: 80}
    assert earliest_built_turn_from_ship_id(50, totals) == 3
    assert earliest_built_turn_from_ship_id(20, totals) == 1
    assert earliest_built_turn_from_ship_id(100, totals) is None


def test_resolve_ship_built_turn_prefers_fleet_over_scoreboard() -> None:
    built, source = resolve_ship_built_turn(
        12,
        fleet_built_turns={12: 7},
        scoreboard_totals_by_turn={1: 5, 5: 20, 7: 30},
    )
    assert built == 7
    assert source == AGE_SOURCE_FLEET_BUILT_TURN

    built, source = resolve_ship_built_turn(
        12,
        fleet_built_turns={},
        scoreboard_totals_by_turn={1: 5, 5: 20, 7: 30},
    )
    assert built == 5
    assert source == AGE_SOURCE_SHIP_ID_SCOREBOARD


def test_travel_turns_and_envelope_radius_warp_square() -> None:
    turn = _load_turn()
    ship = _ship(turn.ships[0], ship_id=1, x=0, y=0, engineid=99)
    engines = {99: _engine(engine_id=99, techlevel=8)}
    hulls = {ship.hullid: _hull(hull_id=ship.hullid, special="")}

    assert travel_turns_at_shell(shell_turn=10, built_turn=7) == 3
    # 3 turns × (warp8² + 1 LY rounding slack)
    radius = travel_envelope_radius_ly(
        ship,
        shell_turn=10,
        built_turn=7,
        hulls_by_id=hulls,
        engines_by_id=engines,
    )
    assert radius == 3.0 * (
        max_travel_distance(8, False) + ENVELOPE_ROUNDING_SLACK_LY_PER_TURN
    )


def test_unknown_engines_assume_warp_9() -> None:
    turn = _load_turn()
    ship = _ship(turn.ships[0], ship_id=1, x=0, y=0, engineid=0)
    assert engine_warp_capability(ship, engines_by_id={}) == 9
    hulls = {ship.hullid: _hull(hull_id=ship.hullid)}
    radius = travel_envelope_radius_ly(
        ship,
        shell_turn=5,
        built_turn=3,
        hulls_by_id=hulls,
        engines_by_id={},
    )
    assert radius == 2.0 * (
        max_travel_distance(9, False) + ENVELOPE_ROUNDING_SLACK_LY_PER_TURN
    )


def test_gravitonic_doubles_envelope_hyperjump_ignored() -> None:
    turn = _load_turn()
    ship = _ship(turn.ships[0], ship_id=1, x=0, y=0, engineid=9, hullid=50)
    engines = {9: _engine(engine_id=9, techlevel=9)}
    grav = {50: _hull(hull_id=50, special="Gravitonic - twice as far")}
    hyp = {50: _hull(hull_id=50, special="Hyperjump - Can jump 350 ly")}

    assert hull_has_hyperjump(hyp[50])
    grav_radius = travel_envelope_radius_ly(
        ship,
        shell_turn=4,
        built_turn=2,
        hulls_by_id=grav,
        engines_by_id=engines,
    )
    assert grav_radius == 2.0 * (
        max_travel_distance(9, True) + ENVELOPE_ROUNDING_SLACK_LY_PER_TURN
    )

    assert (
        travel_envelope_radius_ly(
            ship,
            shell_turn=4,
            built_turn=2,
            hulls_by_id=hyp,
            engines_by_id=engines,
        )
        is None
    )


def test_reachable_sectors_and_unique_envelope_pin() -> None:
    # Ship at origin; sector 0 HW at 50 LY, sector 1 at 200 LY; radius 100 → only sector 0.
    positions = {0: (50.0, 0.0), 1: (200.0, 0.0), 2: (0.0, 200.0)}
    reachable = reachable_sector_indexes(
        ship_x=0,
        ship_y=0,
        radius_ly=100.0,
        sector_positions=positions,
    )
    assert reachable == frozenset({0})

    possible = intersect_owner_possible_sectors(None, reachable)
    assert possible == frozenset({0})
    possible = intersect_owner_possible_sectors(frozenset({0, 1, 2}), reachable)
    assert possible == frozenset({0})

    pinned = apply_unique_sector_envelope_pin(
        {},
        owner_slot=3,
        possible_sectors=possible,
        turn=11,
        ship_id=42,
        radius_ly=100.0,
        age_source=AGE_SOURCE_FLEET_BUILT_TURN,
    )
    assert list(pinned.keys()) == [0]
    members = pinned[0]
    assert len(members) == 1
    assert members[0].owner_slot == 3
    assert members[0].provenances[0].kind == PROVENANCE_SHIP_TRAVEL_ENVELOPE
    assert members[0].provenances[0].ship_id == 42
    assert members[0].provenances[0].turn == 11

    # Two sectors remain → no pin.
    assert (
        apply_unique_sector_envelope_pin(
            {},
            owner_slot=3,
            possible_sectors=frozenset({0, 1}),
            turn=11,
            ship_id=42,
            radius_ly=100.0,
            age_source=AGE_SOURCE_FLEET_BUILT_TURN,
        )
        == {}
    )


def test_preferred_candidate_ownership_and_nearby_merge_ambiguous() -> None:
    turn = _load_turn()
    template = turn.planets[0]
    preferred_planet = _planet(template, planet_id=10, x=0, y=0, ownerid=2)
    nearby_enemy = _planet(template, planet_id=20, x=100, y=0, ownerid=5)
    far_enemy = _planet(template, planet_id=30, x=500, y=0, ownerid=7)
    planets_by_id = {
        10: preferred_planet,
        20: nearby_enemy,
        30: far_enemy,
    }
    preferred = _candidate(10, confidence_tier=CONFIDENCE_DEFINITE)

    sets = apply_preferred_candidate_ownership(
        {},
        sector_index=1,
        preferred=preferred,
        planets_by_id=planets_by_id,
        turn=8,
    )
    assert [m.owner_slot for m in sets[1]] == [2]
    assert sets[1][0].provenances[0].kind == PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP

    sets = apply_nearby_planet_ownership(
        sets,
        sector_index=1,
        candidate_planets=[preferred_planet],
        all_planets=[preferred_planet, nearby_enemy, far_enemy],
        turn=8,
    )
    slots = [m.owner_slot for m in sets[1]]
    assert slots == [2, 5]
    nearby_member = next(m for m in sets[1] if m.owner_slot == 5)
    assert nearby_member.provenances[0].kind == PROVENANCE_NEARBY_PLANET_OWNERSHIP
    assert nearby_member.provenances[0].planet_id == 20
    assert nearby_member.provenances[0].distance_ly == 100.0
    # Far planet outside 162 LY does not join.
    assert 7 not in slots
    assert NEARBY_OWNERSHIP_RADIUS_LY == max_travel_distance(9, True)


def test_ambiguous_owner_set_retains_multiple_provenances() -> None:
    from api.analytics.homeworld_locator.models import OwnershipProvenance

    first = OwnershipProvenance(
        kind=PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP,
        turn=5,
        planet_id=1,
    )
    second = OwnershipProvenance(
        kind=PROVENANCE_SHIP_TRAVEL_ENVELOPE,
        turn=6,
        ship_id=9,
        radius_ly=81.0,
        age_source=AGE_SOURCE_SHIP_ID_SCOREBOARD,
    )
    merged = add_provenance_to_sector_owner_set((), owner_slot=4, provenance=first)
    merged = add_provenance_to_sector_owner_set(merged, owner_slot=2, provenance=second)
    assert [m.owner_slot for m in merged] == [2, 4]
    # Same provenance twice does not duplicate.
    again = add_provenance_to_sector_owner_set(merged, owner_slot=4, provenance=first)
    assert again[1].provenances == (first,)


def test_preferred_candidate_ordering_definite_over_most_probable() -> None:
    rows = (
        _candidate(1, confidence_tier=CONFIDENCE_POSSIBLE),
        _candidate(2, confidence_tier=CONFIDENCE_DEFINITE),
        _candidate(3, confidence_tier=CONFIDENCE_POSSIBLE),
    )
    assert (
        preferred_candidate_in_sector(
            rows,
            most_probable_planet_ids=frozenset({1}),
        ).planet_id
        == 2
    )
    possibles = (
        _candidate(1),
        _candidate(3),
    )
    assert (
        preferred_candidate_in_sector(
            possibles,
            most_probable_planet_ids=frozenset({3}),
        ).planet_id
        == 3
    )


def test_accumulate_ownership_evidence_envelope_pin_and_sightings(template_planet) -> None:
    from api.analytics.homeworld_locator.ownership_refine import (
        accumulate_ownership_evidence_for_turn,
        sector_owner_sets_to_dict,
    )
    from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate

    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550.0
    planets: list[Planet] = []
    for index in range(player_count):
        angle = index * (2.0 * math.pi / player_count)
        planets.append(
            _planet(
                template_planet,
                planet_id=index + 1,
                x=int(round(center[0] + radius * math.cos(angle))),
                y=int(round(center[1] + radius * math.sin(angle))),
                ownerid=5 if index == 1 else 0,
            )
        )
    pin = planets[0]
    ship = _ship(
        _load_turn().ships[0],
        ship_id=42,
        x=int(center[0] + 500),
        y=int(center[1]),
        ownerid=3,
        engineid=9,
    )
    shell = _eligible_geometry_turn(template_planet, planets=planets, ships=[ship])
    shell = replace(shell, engines=[_engine(engine_id=9, techlevel=9)])

    candidates = (
        HomeworldCandidateRecord(
            planet_id=pin.id,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
        ),
        HomeworldCandidateRecord(
            planet_id=planets[1].id,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
        ),
    )
    prior = HomeworldEvidenceAggregate(turn=9, baseline_turn=1)

    sector_owner_sets, owner_possible = accumulate_ownership_evidence_for_turn(
        prior,
        turn=shell,
        candidates=candidates,
        fleet_built_turns={42: 8},
        load_turn=lambda turn_number: shell if turn_number == 10 else None,
        ensure_floor=1,
    )
    by_sector = sector_owner_sets_to_dict(sector_owner_sets)
    assert 0 in by_sector
    assert 3 in [member.owner_slot for member in by_sector[0]]
    assert 5 in [member.owner_slot for member in by_sector[1]]
    preferred_member = next(member for member in by_sector[1] if member.owner_slot == 5)
    assert preferred_member.provenances[0].kind == PROVENANCE_PREFERRED_CANDIDATE_OWNERSHIP
    assert owner_possible == ((3, (0,)),)


def test_sector_owner_sets_serialization_round_trip() -> None:
    from api.analytics.homeworld_locator.models import OwnershipProvenance, SectorOwnerMember
    from api.analytics.homeworld_locator.serialization import (
        homeworld_evidence_aggregate_from_json,
        homeworld_evidence_aggregate_to_json,
    )
    from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate

    member = SectorOwnerMember(
        owner_slot=2,
        provenances=(
            OwnershipProvenance(
                kind=PROVENANCE_SHIP_TRAVEL_ENVELOPE,
                turn=10,
                ship_id=42,
                radius_ly=81.0,
                age_source=AGE_SOURCE_FLEET_BUILT_TURN,
            ),
            OwnershipProvenance(
                kind=PROVENANCE_NEARBY_PLANET_OWNERSHIP,
                turn=10,
                planet_id=20,
                distance_ly=100.0,
            ),
        ),
    )
    aggregate = HomeworldEvidenceAggregate(
        turn=10,
        baseline_turn=1,
        sector_owner_sets=((1, (member,)),),
        owner_possible_sectors=((2, (1,)),),
        evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
    )
    restored = homeworld_evidence_aggregate_from_json(
        homeworld_evidence_aggregate_to_json(aggregate)
    )
    assert restored.sector_owner_sets == aggregate.sector_owner_sets
    assert restored.owner_possible_sectors == aggregate.owner_possible_sectors
    assert restored.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
    wire = homeworld_evidence_aggregate_to_json(aggregate)
    assert wire["evidenceAlgorithmVersion"] == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION


def test_apply_unique_owner_orphan_bind_sets_perspective(template_planet) -> None:
    from api.analytics.homeworld_locator.models import OwnershipProvenance, SectorOwnerMember
    from api.analytics.homeworld_locator.ownership_refine import apply_unique_owner_orphan_bind
    from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate

    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550.0
    planets = []
    for index in range(player_count):
        angle = index * (2.0 * math.pi / player_count)
        planets.append(
            _planet(
                template_planet,
                planet_id=index + 1,
                x=int(round(center[0] + radius * math.cos(angle))),
                y=int(round(center[1] + radius * math.sin(angle))),
            )
        )
    shell = _eligible_geometry_turn(template_planet, planets=planets)
    orphan = HomeworldCandidateRecord(
        planet_id=planets[1].id,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    aggregate = HomeworldEvidenceAggregate(
        turn=10,
        baseline_turn=1,
        sector_owner_sets=(
            (
                1,
                (
                    SectorOwnerMember(
                        owner_slot=4,
                        provenances=(
                            OwnershipProvenance(
                                kind=PROVENANCE_SHIP_TRAVEL_ENVELOPE,
                                turn=10,
                                ship_id=1,
                                radius_ly=50.0,
                                age_source=AGE_SOURCE_FLEET_BUILT_TURN,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    definite = HomeworldCandidateRecord(
        planet_id=planets[0].id,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    bound = apply_unique_owner_orphan_bind(
        (definite, orphan),
        aggregate,
        turn=shell,
    )
    by_id = {row.planet_id: row for row in bound}
    assert by_id[orphan.planet_id].perspective == 4
