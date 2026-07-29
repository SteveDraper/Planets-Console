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
from api.analytics.homeworld_locator.layout_distributions_asset import (
    CategoryLayoutDistributions,
    LayoutDistributionsAsset,
    SmoothedMetricDistribution,
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
    debrisdisk: int = 0,
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
        debrisdisk=debrisdisk,
    )


def _stub_layout_asset(*, support_min: float = 500.0, support_max: float = 600.0):
    mid = 0.5 * (support_min + support_max)
    metric = SmoothedMetricDistribution(
        sample_count=10,
        support_min=support_min,
        support_max=support_max,
        mean=mid,
        std=max(1.0, (support_max - support_min) / 6.0),
    )
    category = CategoryLayoutDistributions(
        center_distance=metric,
        neighbor_separation=metric,
    )
    return LayoutDistributionsAsset(
        schema_version=2,
        bin_width_ly=10.0,
        cost_model="normal_neg_log_density",
        categories={"epic": category, "standard": category},
        source={},
    )


def test_homeworld_locator_config_defaults() -> None:
    cfg = HomeworldLocatorConfig()
    assert cfg.min_baseline_clans == 10_000
    assert cfg.origin_distance_evidence_lambda == 0.95


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
        HW_DISTRIBUTION_ONE_VS_CIRCLE,
        INACTIVE_REASON_NO_HOMEWORLD,
        INACTIVE_REASON_SCENARIO_OVERRIDE,
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
    # Ashes of the Evil Empire: One vs. Circle distribution.
    ashes = replace(sample_settings, hwdistribution=HW_DISTRIBUTION_ONE_VS_CIRCLE)
    assert homeworld_locator_inactive_reason(ashes) == INACTIVE_REASON_SCENARIO_OVERRIDE
    # Crazy Intermix: extra planets with random locations.
    intermix = replace(sample_settings, extraplanets=3, extraplanetsrandomloc=True)
    assert homeworld_locator_inactive_reason(intermix) == INACTIVE_REASON_SCENARIO_OVERRIDE
    # Disunited Kingdoms: extra planets without random locations.
    disunited = replace(sample_settings, extraplanets=3, extraplanetsrandomloc=False)
    assert homeworld_locator_inactive_reason(disunited) == INACTIVE_REASON_SCENARIO_OVERRIDE
    # nohomeworld wins over scenario recipe knobs.
    assert (
        homeworld_locator_inactive_reason(
            replace(ashes, nohomeworld=True, extraplanets=2, extraplanetsrandomloc=True)
        )
        == INACTIVE_REASON_NO_HOMEWORLD
    )
    # Wandering Tribes wins over scenario recipe knobs.
    assert (
        homeworld_locator_inactive_reason(replace(ashes, wanderingtribescount=1))
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


def test_cluster_neighbors_ignore_planetoids(template_planet, sample_settings) -> None:
    candidate = _planet(template_planet, planet_id=1, x=0, y=0)
    neighbors = [
        _planet(template_planet, planet_id=2, x=50, y=0),  # traditional very close
        _planet(template_planet, planet_id=3, x=40, y=0, debrisdisk=1),  # planetoid -- ignored
        _planet(template_planet, planet_id=4, x=100, y=0),  # traditional close band
        _planet(template_planet, planet_id=5, x=120, y=0, debrisdisk=1),  # planetoid -- ignored
    ]
    counts = count_cluster_neighbors(candidate, [candidate, *neighbors])
    assert counts.very_close == 1
    assert counts.close_band == 1


def test_baseline_profile_rejects_planetoid(template_planet, sample_settings) -> None:
    planetoid = _planet(
        template_planet,
        planet_id=1,
        x=0,
        y=0,
        ownerid=1,
        clans=20_000,
        temp=50,
        debrisdisk=1,
    )
    assert not matches_homeworld_baseline_profile(
        planetoid,
        owner_id=1,
        race_id=1,
        settings=replace(sample_settings, homeworldhasstarbase=False),
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
    )


def test_ring_sites_skip_planetoids(template_planet) -> None:
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
    # Planetoid sitting on a rival ring slot must not be chosen.
    planetoid = replace(sites[1], id=99, debrisdisk=1)
    pin = sites[0]
    found = find_circular_ring_homeworld_sites(
        [sites[0], planetoid, sites[2], sites[3]],
        center=center,
        player_count=player_count,
        pin=pin,
    )
    assert {planet.id for planet in found} == {1, 3, 4}
    assert all(planet.debrisdisk == 0 for planet in found)


def test_infer_baseline_never_emits_planetoid_candidates(template_planet, sample_settings) -> None:
    settings = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_RANDOM_SPACED,
        mapshape=MAP_SHAPE_RECTANGULAR,
        homeworldhasstarbase=False,
        verycloseplanets=1,
        closeplanets=1,
    )
    hw = _planet(template_planet, planet_id=1, x=0, y=0, ownerid=1, clans=20_000, temp=50)
    near = _planet(template_planet, planet_id=2, x=50, y=0)
    close = _planet(template_planet, planet_id=3, x=100, y=0)
    planetoid = _planet(
        template_planet,
        planet_id=4,
        x=0,
        y=0,
        ownerid=1,
        clans=20_000,
        temp=50,
        debrisdisk=1,
    )
    # Planetoid that would otherwise look like a cluster-satisfying orphan.
    clusterish_planetoid = _planet(
        template_planet,
        planet_id=5,
        x=500,
        y=0,
        debrisdisk=1,
    )
    clusterish_near = _planet(template_planet, planet_id=6, x=550, y=0)
    clusterish_close = _planet(template_planet, planet_id=7, x=600, y=0)

    candidates = infer_homeworld_baseline_candidates(
        [hw, near, close, planetoid, clusterish_planetoid, clusterish_near, clusterish_close],
        settings=settings,
        viewpoint_player_id=1,
        viewpoint_perspective=1,
        viewpoint_race_id=1,
        player_count=2,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
    )
    ids = {row.planet_id for row in candidates}
    assert 4 not in ids
    assert 5 not in ids
    assert 1 in ids


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
        # Ring sites must also meet cluster (AND). Keep thresholds low and give
        # each ring planet a private very-close satellite so they qualify.
        verycloseplanets=1,
        closeplanets=0,
    )
    center = (2000.0, 2000.0)
    radius = 500.0
    player_count = 4
    ring = []
    satellites = []
    for index in range(player_count):
        angle = index * (2.0 * math.pi / player_count)
        owner = 1 if index == 0 else 0
        clans = 20_000 if index == 0 else 0
        temp = 50 if index == 0 else 0
        x = int(round(center[0] + radius * math.cos(angle)))
        y = int(round(center[1] + radius * math.sin(angle)))
        ring.append(
            _planet(
                template_planet,
                planet_id=index + 1,
                x=x,
                y=y,
                ownerid=owner,
                clans=clans,
                temp=temp,
            )
        )
        # ~40 LY radially outward -- very-close to this ring site only.
        satellites.append(
            _planet(
                template_planet,
                planet_id=100 + index,
                x=int(round(center[0] + (radius + 40.0) * math.cos(angle))),
                y=int(round(center[1] + (radius + 40.0) * math.sin(angle))),
            )
        )

    candidates = infer_homeworld_baseline_candidates(
        [*ring, *satellites],
        settings=settings,
        viewpoint_player_id=1,
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


def test_infer_baseline_ring_site_requires_cluster_constraint(
    template_planet, sample_settings
) -> None:
    """Ring geometry alone is not enough -- cluster minima must also hold (AND)."""
    settings = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        homeworldhasstarbase=False,
        verycloseplanets=2,
        closeplanets=0,
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
    # Only ring site 2 (planet id 2) gets enough very-close neighbors.
    angle_1 = 1 * (2.0 * math.pi / player_count)
    cluster_support = [
        _planet(
            template_planet,
            planet_id=20,
            x=int(round(center[0] + (radius + 30.0) * math.cos(angle_1))),
            y=int(round(center[1] + (radius + 30.0) * math.sin(angle_1))),
        ),
        _planet(
            template_planet,
            planet_id=21,
            x=int(round(center[0] + (radius + 50.0) * math.cos(angle_1))),
            y=int(round(center[1] + (radius + 50.0) * math.sin(angle_1))),
        ),
    ]

    candidates = infer_homeworld_baseline_candidates(
        [*ring, *cluster_support],
        settings=settings,
        viewpoint_player_id=1,
        viewpoint_perspective=1,
        viewpoint_race_id=1,
        player_count=player_count,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
        map_center=center,
    )
    by_id = {row.planet_id: row for row in candidates}
    assert by_id[1].confidence_tier == CONFIDENCE_DEFINITE
    assert 2 in by_id and by_id[2].confidence_tier == CONFIDENCE_POSSIBLE
    # Ring-nearest planets 3 and 4 fail verycloseplanets=2 -- must not emit.
    assert 3 not in by_id
    assert 4 not in by_id


def test_cull_co_sector_candidates_drops_possibles_near_definite(
    template_planet,
) -> None:
    from api.analytics.homeworld_locator.baseline import (
        cull_co_sector_candidates_after_definites,
    )
    from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
    from api.analytics.homeworld_locator.types import HomeworldCandidateRecord

    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=1, x=500, y=0)
    co_sector = _planet(template_planet, planet_id=2, x=550, y=20)
    other_sector = _planet(template_planet, planet_id=3, x=0, y=500)
    planets_by_id = {1: pin, 2: co_sector, 3: other_sector}
    rows = (
        HomeworldCandidateRecord(
            planet_id=1,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=2,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=3,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
        ),
    )
    culled = cull_co_sector_candidates_after_definites(
        rows,
        planets_by_id,
        center=center,
        player_count=4,
        pin_angle=0.0,
    )
    assert {row.planet_id for row in culled} == {1, 3}


def test_cull_co_sector_drops_extra_inferred_definites(template_planet) -> None:
    """Evidence-promoted orphan definites must not coexist with the sector pin."""
    from api.analytics.homeworld_locator.baseline import (
        cull_co_sector_candidates_after_definites,
    )
    from api.analytics.homeworld_locator.constants import ATTRIBUTION_INFERRED
    from api.analytics.homeworld_locator.types import HomeworldCandidateRecord

    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=182, x=500, y=0)
    orphan_a = _planet(template_planet, planet_id=10, x=520, y=15)
    orphan_b = _planet(template_planet, planet_id=74, x=480, y=30)
    neighbor = _planet(template_planet, planet_id=54, x=400, y=350)
    planets_by_id = {182: pin, 10: orphan_a, 74: orphan_b, 54: neighbor}
    rows = (
        HomeworldCandidateRecord(
            planet_id=182,
            perspective=2,
            confidence_tier=CONFIDENCE_DEFINITE,
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=10,
            perspective=None,
            confidence_tier=CONFIDENCE_DEFINITE,
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=74,
            perspective=None,
            confidence_tier=CONFIDENCE_DEFINITE,
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=54,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_INFERRED,
        ),
    )
    culled = cull_co_sector_candidates_after_definites(
        rows,
        planets_by_id,
        center=center,
        player_count=11,
        pin_angle=0.0,
    )
    assert {row.planet_id for row in culled} == {182, 54}
    pin_row = next(row for row in culled if row.planet_id == 182)
    assert pin_row.confidence_tier == CONFIDENCE_DEFINITE


def test_cull_preserves_user_asserted_co_sector_possible(template_planet) -> None:
    from api.analytics.homeworld_locator.baseline import (
        cull_co_sector_candidates_after_definites,
    )
    from api.analytics.homeworld_locator.constants import (
        ATTRIBUTION_INFERRED,
        ATTRIBUTION_USER_ASSERTED,
    )
    from api.analytics.homeworld_locator.types import HomeworldCandidateRecord

    center = (0.0, 0.0)
    pin = _planet(template_planet, planet_id=1, x=500, y=0)
    asserted = _planet(template_planet, planet_id=2, x=550, y=20)
    rows = (
        HomeworldCandidateRecord(
            planet_id=1,
            perspective=1,
            confidence_tier=CONFIDENCE_DEFINITE,
            attribution=ATTRIBUTION_INFERRED,
        ),
        HomeworldCandidateRecord(
            planet_id=2,
            perspective=None,
            confidence_tier=CONFIDENCE_POSSIBLE,
            attribution=ATTRIBUTION_USER_ASSERTED,
        ),
    )
    culled = cull_co_sector_candidates_after_definites(
        rows,
        {1: pin, 2: asserted},
        center=center,
        player_count=4,
        pin_angle=0.0,
    )
    assert {row.planet_id for row in culled} == {1, 2}


def test_infer_baseline_culls_co_sector_cluster_orphans(template_planet, sample_settings) -> None:
    """Cluster orphans in the definite pin's sector are removed; other sectors kept."""
    settings = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        homeworldhasstarbase=False,
        verycloseplanets=1,
        closeplanets=1,
    )
    center = (0.0, 0.0)
    pin = _planet(
        template_planet,
        planet_id=1,
        x=500,
        y=0,
        ownerid=1,
        clans=20_000,
        temp=50,
    )
    # Neighbors that make ``co_sector`` satisfy the cluster constraint, all in sector 0.
    co_sector = _planet(template_planet, planet_id=2, x=500, y=40)
    band_near = _planet(template_planet, planet_id=3, x=520, y=0)  # ~20 LY from co_sector
    band_close = _planet(template_planet, planet_id=4, x=500, y=140)  # ~100 LY from co_sector
    # Opposite sector cluster orphan.
    opposite = _planet(template_planet, planet_id=5, x=-500, y=0)
    opp_near = _planet(template_planet, planet_id=6, x=-520, y=0)
    opp_close = _planet(template_planet, planet_id=7, x=-500, y=140)

    candidates = infer_homeworld_baseline_candidates(
        [pin, co_sector, band_near, band_close, opposite, opp_near, opp_close],
        settings=settings,
        viewpoint_player_id=1,
        viewpoint_perspective=1,
        viewpoint_race_id=1,
        player_count=2,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
        map_center=center,
    )
    ids = {row.planet_id for row in candidates}
    assert 1 in ids
    assert 2 not in ids  # co-sector orphan culled
    assert 5 in ids  # opposite-sector orphan kept
    assert next(row for row in candidates if row.planet_id == 1).confidence_tier == (
        CONFIDENCE_DEFINITE
    )


def test_infer_baseline_culls_orphans_outside_layout_center_band(
    template_planet, sample_settings
) -> None:
    """Epic|standard circular orphans must lie in the layout center-distance band."""
    settings = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_CIRCULAR,
        mapshape=MAP_SHAPE_ROUND,
        homeworldhasstarbase=False,
        verycloseplanets=1,
        closeplanets=1,
        shiplimit=500,
        endturn=100,
        campaignmode=False,
    )
    center = (0.0, 0.0)
    pin = _planet(
        template_planet,
        planet_id=1,
        x=550,
        y=0,
        ownerid=1,
        clans=20_000,
        temp=50,
    )
    # In-band opposite-sector orphan (~550 LY from C).
    in_band = _planet(template_planet, planet_id=5, x=-550, y=0)
    in_near = _planet(template_planet, planet_id=6, x=-570, y=0)
    in_close = _planet(template_planet, planet_id=7, x=-550, y=140)
    # Out-of-band cluster orphan (~300 LY from C; below supportMin 500).
    out_band = _planet(template_planet, planet_id=15, x=-300, y=0)
    out_near = _planet(template_planet, planet_id=16, x=-320, y=0)
    out_close = _planet(template_planet, planet_id=17, x=-300, y=140)

    candidates = infer_homeworld_baseline_candidates(
        [pin, in_band, in_near, in_close, out_band, out_near, out_close],
        settings=settings,
        viewpoint_player_id=1,
        viewpoint_perspective=1,
        viewpoint_race_id=1,
        player_count=11,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
        map_center=center,
        layout_asset=_stub_layout_asset(support_min=500.0, support_max=600.0),
    )
    ids = {row.planet_id for row in candidates}
    assert 1 in ids
    assert 5 in ids
    assert 15 not in ids


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
        viewpoint_player_id=1,
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


def test_infer_baseline_player_id_distinct_from_perspective_slot(
    template_planet, sample_settings
) -> None:
    """Domain matches ownerid (Player.id) but emits the shell perspective slot."""
    settings = replace(
        sample_settings,
        hwdistribution=HW_DISTRIBUTION_RANDOM_SPACED,
        mapshape=MAP_SHAPE_ROUND,
        homeworldhasstarbase=False,
        verycloseplanets=99,
        closeplanets=99,
    )
    viewpoint_player_id = 99
    viewpoint_perspective = 3
    hw = _planet(
        template_planet,
        planet_id=10,
        x=0,
        y=0,
        ownerid=viewpoint_player_id,
        clans=20_000,
        temp=50,
    )
    decoy = _planet(template_planet, planet_id=11, x=400, y=0)

    candidates = infer_homeworld_baseline_candidates(
        [hw, decoy],
        settings=settings,
        viewpoint_player_id=viewpoint_player_id,
        viewpoint_perspective=viewpoint_perspective,
        viewpoint_race_id=1,
        player_count=4,
        starbase_planet_ids=set(),
        min_baseline_clans=10_000,
    )
    assert len(candidates) == 1
    assert candidates[0].planet_id == 10
    assert candidates[0].perspective == viewpoint_perspective
    assert candidates[0].perspective != viewpoint_player_id
    assert candidates[0].confidence_tier == CONFIDENCE_DEFINITE
