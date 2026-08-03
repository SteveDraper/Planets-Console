"""Unit tests for homeworld locator location evidence domain."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from api.analytics.homeworld_locator.location_evidence import (
    ORIGIN_DISTANCE_MATCH_TOLERANCE_LY,
    candidate_planet_ids,
    origin_distance_candidate_planet_ids,
    origin_distance_targets,
    promote_candidate_to_definite,
    record_single_starbase_promotion,
    scoreboard_starbase_count_for_owner,
    ship_at_planet,
    ship_gravitonic_movement,
    ship_matches_origin_distance_to_planet,
    single_starbase_new_build_implicated_planet_id,
    upsert_origin_distance_observation,
)
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    OriginDistanceObservation,
)
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord
from api.concepts.hull_abilities import hull_has_gravitonic_movement
from api.concepts.planet_connections.wells import max_travel_distance
from api.models.components import Hull
from api.models.planet import Planet
from api.models.ship import Ship
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _load_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


def _planet(template: Planet, *, planet_id: int, x: int, y: int) -> Planet:
    return replace(template, id=planet_id, name=f"P{planet_id}", x=x, y=y)


def _ship(template: Ship, *, ship_id: int, x: int, y: int, ownerid: int = 2, turn: int = 0) -> Ship:
    return replace(template, id=ship_id, x=x, y=y, ownerid=ownerid, turn=turn)


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


def _candidate(planet_id: int, *, perspective: int | None = 1) -> HomeworldCandidateRecord:
    return HomeworldCandidateRecord(
        planet_id=planet_id,
        perspective=perspective,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )


def _turn_with_owner_starbase_count(
    turn,
    *,
    owner_id: int,
    starbases: int,
    stealthmode: bool = False,
):
    scores = [
        replace(score, starbases=starbases) if score.ownerid == owner_id else score
        for score in turn.scores
    ]
    if not any(score.ownerid == owner_id for score in scores):
        template = scores[0]
        scores = [
            *scores,
            replace(template, ownerid=owner_id, starbases=starbases),
        ]
    return replace(turn, settings=replace(turn.settings, stealthmode=stealthmode), scores=scores)


def test_origin_distance_targets_use_max_travel_distance() -> None:
    assert origin_distance_targets(gravitonic_movement=False) == (
        max_travel_distance(8, False),
        max_travel_distance(9, False),
    )
    assert origin_distance_targets(gravitonic_movement=True) == (
        max_travel_distance(8, True),
        max_travel_distance(9, True),
    )


def test_origin_distance_band_tolerance() -> None:
    turn = _load_turn()
    planet = _planet(turn.planets[0], planet_id=100, x=1000, y=1000)
    ship_template = turn.ships[0]

    warp8 = max_travel_distance(8, False)
    ship = _ship(ship_template, ship_id=1, x=1000 + int(warp8), y=1000)
    assert ship_matches_origin_distance_to_planet(ship, planet, gravitonic_movement=False)

    ship_edge = _ship(
        ship_template,
        ship_id=2,
        x=1000 + int(warp8 + ORIGIN_DISTANCE_MATCH_TOLERANCE_LY),
        y=1000,
    )
    assert ship_matches_origin_distance_to_planet(ship_edge, planet, gravitonic_movement=False)

    ship_outside = _ship(
        ship_template,
        ship_id=3,
        x=1000 + int(warp8 + ORIGIN_DISTANCE_MATCH_TOLERANCE_LY + 1),
        y=1000,
    )
    assert not ship_matches_origin_distance_to_planet(
        ship_outside,
        planet,
        gravitonic_movement=False,
    )


def test_gravitonic_bands_apply_only_to_gravitonic_hulls() -> None:
    turn = _load_turn()
    planet = _planet(turn.planets[0], planet_id=100, x=0, y=0)
    ship_template = turn.ships[0]
    grav_warp8 = max_travel_distance(8, True)

    ship = _ship(ship_template, ship_id=1, x=int(grav_warp8), y=0)
    assert not ship_matches_origin_distance_to_planet(ship, planet, gravitonic_movement=False)
    assert ship_matches_origin_distance_to_planet(ship, planet, gravitonic_movement=True)


def test_hull_has_gravitonic_movement_from_special() -> None:
    gravitonic = _hull(
        hull_id=1,
        special="Gravitonic - This ship moves twice as far as normal ships.",
    )
    regular = _hull(hull_id=2, special="")
    assert hull_has_gravitonic_movement(gravitonic)
    assert not hull_has_gravitonic_movement(regular)


def test_origin_distance_matches_existing_candidates_only() -> None:
    turn = _load_turn()
    ship_template = turn.ships[0]
    hw_planet = _planet(turn.planets[0], planet_id=10, x=500, y=500)
    non_candidate_planet = _planet(turn.planets[0], planet_id=20, x=700, y=500)
    planets_by_id = {10: hw_planet, 20: non_candidate_planet}
    warp8 = max_travel_distance(8, False)

    ship_near_non_candidate = _ship(ship_template, ship_id=1, x=700 + int(warp8), y=500)
    matched = origin_distance_candidate_planet_ids(
        ship_near_non_candidate,
        candidate_planet_ids=candidate_planet_ids((_candidate(10),)),
        planets_by_id=planets_by_id,
        gravitonic_movement=False,
    )
    assert matched == ()

    ship_near_candidate = _ship(ship_template, ship_id=2, x=500 + int(warp8), y=500)
    matched = origin_distance_candidate_planet_ids(
        ship_near_candidate,
        candidate_planet_ids=candidate_planet_ids((_candidate(10),)),
        planets_by_id=planets_by_id,
        gravitonic_movement=False,
    )
    assert matched == (10,)


def test_origin_distance_observation_upsert_by_location() -> None:
    """Two locations → two observations; same coords → one with unioned M."""
    first = upsert_origin_distance_observation(
        (),
        turn=5,
        x=100,
        y=200,
        matched_planet_ids=(10,),
    )
    assert first == (OriginDistanceObservation(turn=5, x=100, y=200, matched_planet_ids=(10,)),)
    two_locations = upsert_origin_distance_observation(
        first,
        turn=5,
        x=300,
        y=400,
        matched_planet_ids=(10,),
    )
    assert two_locations == (
        OriginDistanceObservation(turn=5, x=100, y=200, matched_planet_ids=(10,)),
        OriginDistanceObservation(turn=5, x=300, y=400, matched_planet_ids=(10,)),
    )
    colocated_union = upsert_origin_distance_observation(
        two_locations,
        turn=5,
        x=100,
        y=200,
        matched_planet_ids=(11, 10),
    )
    assert colocated_union == (
        OriginDistanceObservation(turn=5, x=100, y=200, matched_planet_ids=(10, 11)),
        OriginDistanceObservation(turn=5, x=300, y=400, matched_planet_ids=(10,)),
    )
    ambiguous = upsert_origin_distance_observation(
        (),
        turn=12,
        x=50,
        y=60,
        matched_planet_ids=(483, 435),
    )
    assert ambiguous == (
        OriginDistanceObservation(turn=12, x=50, y=60, matched_planet_ids=(435, 483)),
    )
    assert len(ambiguous[0].matched_planet_ids) == 2
    empty = upsert_origin_distance_observation(
        first,
        turn=5,
        x=1,
        y=2,
        matched_planet_ids=(),
    )
    assert empty == first


def test_single_starbase_new_build_promotes_possible_to_definite() -> None:
    candidates = (
        _candidate(10, perspective=None),
        HomeworldCandidateRecord(
            planet_id=20,
            perspective=2,
            confidence_tier=CONFIDENCE_DEFINITE,
        ),
    )
    promoted = promote_candidate_to_definite(candidates, planet_id=10)
    assert promoted[0].confidence_tier == CONFIDENCE_DEFINITE
    assert promoted[0].perspective is None
    assert promoted[1] == candidates[1]


def test_single_starbase_new_build_implicates_at_planet_candidate() -> None:
    turn = _turn_with_owner_starbase_count(_load_turn(), owner_id=2, starbases=1)
    ship_template = turn.ships[0]
    hw_planet = _planet(turn.planets[0], planet_id=10, x=300, y=300)
    planets_by_id = {10: hw_planet}
    ship = _ship(ship_template, ship_id=99, x=300, y=300, ownerid=2, turn=4)

    planet_id = single_starbase_new_build_implicated_planet_id(
        ship,
        turn,
        shell_turn=5,
        candidate_planet_ids=candidate_planet_ids((_candidate(10),)),
        planets_by_id=planets_by_id,
    )
    assert planet_id == 10


def test_single_starbase_new_build_skips_stealth_starbase_count() -> None:
    turn = _turn_with_owner_starbase_count(_load_turn(), owner_id=2, starbases=1, stealthmode=True)
    assert scoreboard_starbase_count_for_owner(turn, owner_id=2) is None

    ship_template = turn.ships[0]
    hw_planet = _planet(turn.planets[0], planet_id=10, x=300, y=300)
    ship = _ship(ship_template, ship_id=99, x=300, y=300, ownerid=2, turn=4)
    assert (
        single_starbase_new_build_implicated_planet_id(
            ship,
            turn,
            shell_turn=5,
            candidate_planet_ids=candidate_planet_ids((_candidate(10),)),
            planets_by_id={10: hw_planet},
        )
        is None
    )


def test_single_starbase_new_build_skips_when_starbase_count_not_one() -> None:
    turn = _turn_with_owner_starbase_count(_load_turn(), owner_id=2, starbases=2)
    ship_template = turn.ships[0]
    hw_planet = _planet(turn.planets[0], planet_id=10, x=300, y=300)
    ship = _ship(ship_template, ship_id=99, x=300, y=300, ownerid=2, turn=4)

    assert (
        single_starbase_new_build_implicated_planet_id(
            ship,
            turn,
            shell_turn=5,
            candidate_planet_ids=candidate_planet_ids((_candidate(10),)),
            planets_by_id={10: hw_planet},
        )
        is None
    )


def test_single_starbase_new_build_accepts_fleet_built_turn() -> None:
    turn = _turn_with_owner_starbase_count(_load_turn(), owner_id=2, starbases=1)
    ship_template = turn.ships[0]
    hw_planet = _planet(turn.planets[0], planet_id=10, x=300, y=300)
    ship = _ship(ship_template, ship_id=99, x=300, y=300, ownerid=2, turn=0)

    planet_id = single_starbase_new_build_implicated_planet_id(
        ship,
        turn,
        shell_turn=5,
        candidate_planet_ids=candidate_planet_ids((_candidate(10),)),
        planets_by_id={10: hw_planet},
        fleet_built_turn=4,
    )
    assert planet_id == 10


def test_single_starbase_promotion_does_not_assign_homeworld_owner_from_ship_owner() -> None:
    turn = _turn_with_owner_starbase_count(_load_turn(), owner_id=7, starbases=1)
    ship_template = turn.ships[0]
    orphan = _candidate(10, perspective=None)
    hw_planet = _planet(turn.planets[0], planet_id=10, x=300, y=300)
    ship = _ship(ship_template, ship_id=99, x=300, y=300, ownerid=7, turn=4)

    planet_id = single_starbase_new_build_implicated_planet_id(
        ship,
        turn,
        shell_turn=5,
        candidate_planet_ids=candidate_planet_ids((orphan,)),
        planets_by_id={10: hw_planet},
    )
    assert planet_id == 10
    promoted = promote_candidate_to_definite((orphan,), planet_id=planet_id)
    assert promoted[0].perspective is None


def test_ship_gravitonic_movement_uses_turn_hull_catalog() -> None:
    turn = _load_turn()
    ship_template = turn.ships[0]
    gravitonic_hull = _hull(hull_id=77, special="Gravitonic")
    ship = replace(ship_template, hullid=77)
    hulls_by_id = {77: gravitonic_hull}
    assert ship_gravitonic_movement(ship, hulls_by_id=hulls_by_id)


def test_ship_at_planet_requires_exact_coordinates() -> None:
    turn = _load_turn()
    planet = _planet(turn.planets[0], planet_id=1, x=10, y=20)
    ship_template = turn.ships[0]
    assert ship_at_planet(_ship(ship_template, ship_id=1, x=10, y=20), planet)
    assert not ship_at_planet(_ship(ship_template, ship_id=2, x=11, y=20), planet)


def test_record_single_starbase_promotion_dedupes_per_planet_turn() -> None:
    first = record_single_starbase_promotion((), turn=5, planet_id=10)
    second = record_single_starbase_promotion(first, turn=5, planet_id=10)
    assert first == second
    assert len(first) == 1


def test_baseline_profile_location_provenances_mints_strong() -> None:
    from api.analytics.homeworld_locator.location_evidence import (
        baseline_profile_location_provenances,
    )
    from api.analytics.homeworld_locator.models import (
        PROVENANCE_BASELINE_PROFILE,
        LocationProvenance,
    )

    rows = baseline_profile_location_provenances(
        baseline_turn=1,
        definite_planet_ids=(20, 10, 10),
    )
    assert rows == (
        LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
        LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=20),
    )


def test_collect_machine_location_provenances_mints_v1_kinds() -> None:
    from api.analytics.homeworld_locator.location_evidence import (
        collect_machine_location_provenances,
    )
    from api.analytics.homeworld_locator.models import (
        EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD,
        PROVENANCE_BASELINE_PROFILE,
        PROVENANCE_ORIGIN_DISTANCE,
        HomeworldSingleStarbasePromotion,
        LocationProvenance,
    )

    prior = (
        LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=10),
        # Stale OD/SB on prior must be rebuilt from collections, not carried.
        LocationProvenance(kind=PROVENANCE_ORIGIN_DISTANCE, turn=2, planet_id=99),
    )
    collected = collect_machine_location_provenances(
        prior_location_provenances=prior,
        origin_distance_observations=(
            OriginDistanceObservation(turn=3, x=1, y=2, matched_planet_ids=(10, 20)),
            OriginDistanceObservation(turn=3, x=5, y=6, matched_planet_ids=(10,)),
        ),
        single_starbase_promotions=(
            HomeworldSingleStarbasePromotion(planet_id=20, turn=4),
            HomeworldSingleStarbasePromotion(planet_id=20, turn=4),
        ),
    )
    kinds_by_planet = {(row.kind, row.planet_id, row.turn) for row in collected}
    assert (PROVENANCE_BASELINE_PROFILE, 10, 1) in kinds_by_planet
    assert (PROVENANCE_ORIGIN_DISTANCE, 10, 3) in kinds_by_planet
    assert (PROVENANCE_ORIGIN_DISTANCE, 20, 3) in kinds_by_planet
    assert (EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD, 20, 4) in kinds_by_planet
    assert (PROVENANCE_ORIGIN_DISTANCE, 99, 2) not in kinds_by_planet
    sb_rows = [row for row in collected if row.kind == EVIDENCE_KIND_SINGLE_STARBASE_NEW_BUILD]
    assert len(sb_rows) == 1
