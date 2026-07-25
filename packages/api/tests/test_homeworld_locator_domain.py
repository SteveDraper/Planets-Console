"""Unit tests for homeworld locator pure-domain baseline inference."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    cluster_constraint_deficit,
    count_cluster_neighbors,
    find_circular_ring_homeworld_sites,
    infer_homeworld_baseline_candidates,
    matches_homeworld_baseline_profile,
    meets_homeworld_cluster_constraint,
    unique_baseline_profile_match,
)
from api.concepts.homeworld_layout import (
    HW_DISTRIBUTION_CIRCULAR,
    HW_DISTRIBUTION_RANDOM_SPACED,
    MAP_SHAPE_RECTANGULAR,
    MAP_SHAPE_ROUND,
    supports_circular_round_candidate_geometry,
)
from api.config import HomeworldLocatorConfig
from api.models.planet import Planet
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def template_planet() -> Planet:
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    turn = turn_info_from_json(raw, settings_defaults=raw["settings"])
    return turn.planets[0]


@pytest.fixture
def sample_settings():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    turn = turn_info_from_json(raw, settings_defaults=raw["settings"])
    return turn.settings


def _planet(
    template: Planet,
    *,
    planet_id: int,
    x: int,
    y: int,
    ownerid: int = 0,
    clans: int = 0,
    temp: int = 0,
) -> Planet:
    return replace(
        template,
        id=planet_id,
        name=f"P{planet_id}",
        x=x,
        y=y,
        ownerid=ownerid,
        clans=clans,
        temp=temp,
    )


def test_homeworld_locator_config_defaults() -> None:
    cfg = HomeworldLocatorConfig()
    assert cfg.min_baseline_clans == 10_000
    assert cfg.evidence_promotion_threshold == 2


def test_supports_circular_round_only(sample_settings) -> None:
    circular_round = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
    )
    assert supports_circular_round_candidate_geometry(circular_round) is True
    assert (
        supports_circular_round_candidate_geometry(
            replace(circular_round, hwdistribution=HW_DISTRIBUTION_RANDOM_SPACED)
        )
        is False
    )
    assert (
        supports_circular_round_candidate_geometry(
            replace(circular_round, mapshape=MAP_SHAPE_RECTANGULAR)
        )
        is False
    )


def test_availability_helpers(sample_settings) -> None:
    from api.concepts.homeworld_layout import (
        INACTIVE_REASON_NO_HOMEWORLD,
        INACTIVE_REASON_WANDERING_TRIBES,
        homeworld_locator_inactive_reason,
        is_homeworld_locator_available,
    )

    assert is_homeworld_locator_available(sample_settings) is True
    assert homeworld_locator_inactive_reason(replace(sample_settings, nohomeworld=True)) == (
        INACTIVE_REASON_NO_HOMEWORLD
    )
    assert (
        homeworld_locator_inactive_reason(replace(sample_settings, wanderingtribescount=1))
        == INACTIVE_REASON_WANDERING_TRIBES
    )


def test_matches_baseline_profile_requires_all_signals(template_planet, sample_settings) -> None:
    settings = replace(sample_settings, homeworldhasstarbase=True)
    planet = _planet(
        template_planet,
        planet_id=1,
        x=100,
        y=100,
        ownerid=3,
        clans=12_000,
        temp=50,
    )
    assert matches_homeworld_baseline_profile(
        planet,
        owner_id=3,
        race_id=1,
        settings=settings,
        starbase_planet_ids={1},
        min_baseline_clans=10_000,
    )
    assert not matches_homeworld_baseline_profile(
        planet,
        owner_id=2,
        race_id=1,
        settings=settings,
        starbase_planet_ids={1},
        min_baseline_clans=10_000,
    )
    assert not matches_homeworld_baseline_profile(
        replace(planet, clans=500),
        owner_id=3,
        race_id=1,
        settings=settings,
        starbase_planet_ids={1},
        min_baseline_clans=10_000,
    )
    assert not matches_homeworld_baseline_profile(
        planet,
        owner_id=3,
        race_id=1,
        settings=settings,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
    )
    assert not matches_homeworld_baseline_profile(
        replace(planet, temp=40),
        owner_id=3,
        race_id=1,
        settings=settings,
        starbase_planet_ids={1},
        min_baseline_clans=10_000,
    )


def test_matches_baseline_profile_crystal_prefers_100(template_planet, sample_settings) -> None:
    settings = replace(sample_settings, homeworldhasstarbase=False)
    planet = _planet(
        template_planet,
        planet_id=7,
        x=0,
        y=0,
        ownerid=2,
        clans=15_000,
        temp=100,
    )
    assert matches_homeworld_baseline_profile(
        planet,
        owner_id=2,
        race_id=7,
        settings=settings,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
    )
    assert not matches_homeworld_baseline_profile(
        replace(planet, temp=50),
        owner_id=2,
        race_id=7,
        settings=settings,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
    )


def test_unique_baseline_profile_match_requires_exactly_one(
    template_planet, sample_settings
) -> None:
    settings = replace(sample_settings, homeworldhasstarbase=False)
    a = _planet(template_planet, planet_id=1, x=0, y=0, ownerid=1, clans=20_000, temp=50)
    b = _planet(template_planet, planet_id=2, x=10, y=10, ownerid=1, clans=20_000, temp=50)
    assert (
        unique_baseline_profile_match(
            [a],
            owner_id=1,
            race_id=1,
            settings=settings,
            starbase_planet_ids=set(),
            min_baseline_clans=10_000,
        )
        is a
    )
    assert (
        unique_baseline_profile_match(
            [a, b],
            owner_id=1,
            race_id=1,
            settings=settings,
            starbase_planet_ids=set(),
            min_baseline_clans=10_000,
        )
        is None
    )


def test_cluster_neighbor_bands_and_deficit(template_planet, sample_settings) -> None:
    candidate = _planet(template_planet, planet_id=1, x=0, y=0)
    neighbors = [
        _planet(template_planet, planet_id=2, x=50, y=0),  # very close
        _planet(template_planet, planet_id=3, x=80, y=0),  # very close
        _planet(template_planet, planet_id=4, x=100, y=0),  # close band
        _planet(template_planet, planet_id=5, x=162, y=0),  # close band outer edge
        _planet(template_planet, planet_id=6, x=200, y=0),  # outside
    ]
    counts = count_cluster_neighbors(candidate, [candidate, *neighbors])
    assert counts.very_close == 2
    assert counts.close_band == 2

    settings = replace(sample_settings, verycloseplanets=2, closeplanets=2)
    assert meets_homeworld_cluster_constraint(counts, settings)
    assert cluster_constraint_deficit(counts, settings) == 0

    strict = replace(sample_settings, verycloseplanets=3, closeplanets=4)
    assert not meets_homeworld_cluster_constraint(counts, strict)
    assert cluster_constraint_deficit(counts, strict) == 3


def test_find_circular_ring_sites_from_pin(template_planet) -> None:
    center = (0.0, 0.0)
    radius = 100.0
    player_count = 4
    sites = []
    for index in range(player_count):
        angle = index * (2.0 * math.pi / player_count)
        sites.append(
            _planet(
                template_planet,
                planet_id=index + 1,
                x=int(round(radius * math.cos(angle))),
                y=int(round(radius * math.sin(angle))),
            )
        )
    # decoy off the ring
    decoy = _planet(template_planet, planet_id=99, x=0, y=0)
    pin = sites[0]
    found = find_circular_ring_homeworld_sites(
        [*sites, decoy],
        center=center,
        player_count=player_count,
        pin=pin,
    )
    assert found[0] is pin
    assert {planet.id for planet in found} == {1, 2, 3, 4}


def test_infer_baseline_viewpoint_definite_and_ring_orphans(
    template_planet, sample_settings
) -> None:
    settings = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        homeworldhasstarbase=False,
        verycloseplanets=99,  # prevent cluster orphans from noise planets
        closeplanets=99,
    )
    center = (2000.0, 2000.0)
    radius = 500.0
    player_count = 4
    ring = []
    for index in range(player_count):
        angle = index * (2.0 * math.pi / player_count)
        owner = 1 if index == 0 else 0
        clans = 20_000 if index == 0 else 0
        temp = 50 if index == 0 else 0
        ring.append(
            _planet(
                template_planet,
                planet_id=index + 1,
                x=int(round(center[0] + radius * math.cos(angle))),
                y=int(round(center[1] + radius * math.sin(angle))),
                ownerid=owner,
                clans=clans,
                temp=temp,
            )
        )

    candidates = infer_homeworld_baseline_candidates(
        ring,
        settings=settings,
        viewpoint_perspective=1,
        viewpoint_race_id=1,
        player_count=player_count,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
        map_center=center,
    )
    by_id = {row.planet_id: row for row in candidates}
    assert by_id[1].confidence_tier == CONFIDENCE_DEFINITE
    assert by_id[1].perspective == 1
    for planet_id in (2, 3, 4):
        assert by_id[planet_id].confidence_tier == CONFIDENCE_POSSIBLE
        assert by_id[planet_id].perspective is None


def test_infer_baseline_non_circular_uses_cluster_orphans_only(
    template_planet, sample_settings
) -> None:
    settings = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_RANDOM_SPACED,
        mapshape=MAP_SHAPE_ROUND,
        homeworldhasstarbase=False,
        verycloseplanets=1,
        closeplanets=1,
    )
    hw = _planet(
        template_planet,
        planet_id=10,
        x=0,
        y=0,
        ownerid=1,
        clans=20_000,
        temp=50,
    )
    near = _planet(template_planet, planet_id=11, x=40, y=0)
    mid = _planet(template_planet, planet_id=12, x=120, y=0)
    far = _planet(template_planet, planet_id=13, x=400, y=0)

    candidates = infer_homeworld_baseline_candidates(
        [hw, near, mid, far],
        settings=settings,
        viewpoint_perspective=1,
        viewpoint_race_id=1,
        player_count=4,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
        map_center=(0.0, 0.0),
    )
    by_id = {row.planet_id: row for row in candidates}
    assert by_id[10].confidence_tier == CONFIDENCE_DEFINITE
    assert by_id[10].perspective == 1
    # near has mid in close band and no very-close except... wait near is neighbor of hw.
    # cluster orphans: planets meeting both minima that aren't already emitted.
    # hw already emitted. near: neighbors = hw (40), mid (80), far (360)
    #   very_close: hw(40), mid(80) => 2; close: none with d in (81,162] — mid is 80 <=81
    # Actually mid at 80 from near is very close. far at 360 outside.
    # near may or may not meet closeplanets=1.
    # mid: neighbors hw(120), near(80), far(280) → very_close: near; close: hw → meets
    assert 13 not in by_id
    assert by_id[12].perspective is None
    assert by_id[12].confidence_tier == CONFIDENCE_POSSIBLE
