"""Unit tests for homeworld cluster FoW density credit (#275)."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.cluster import count_cluster_neighbors
from api.analytics.homeworld_locator.cluster_fow_credit import (
    ClusterFowBandCredit,
    capped_cluster_fow_credit,
    cluster_band_fow_credit,
    cluster_constraint_deficit_with_credit,
    estimate_traditional_planet_density,
    max_traditional_planet_spacing_ly,
    meets_homeworld_cluster_constraint_with_credit,
    populated_map_geometric_area_ly2,
    unobserved_annulus_area_ly2,
)
from api.analytics.homeworld_locator.models import ClusterNeighborCounts
from api.concepts.homeworld_layout import MAP_SHAPE_RECTANGULAR, MAP_SHAPE_ROUND
from api.concepts.map_region_coverage import CoverageOrigin
from api.models.planet import Planet
from api.models.space import Nebula
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
    debrisdisk: int = 0,
) -> Planet:
    return replace(template, id=planet_id, x=x, y=y, debrisdisk=debrisdisk)


def test_round_map_area_uses_pi_r_squared_from_max_spacing(
    template_planet, sample_settings
) -> None:
    settings = replace(sample_settings, mapshape=MAP_SHAPE_ROUND, mapwidth=4000, mapheight=4000)
    planets = [
        _planet(template_planet, planet_id=1, x=0, y=0),
        _planet(template_planet, planet_id=2, x=200, y=0),
    ]
    diameter = max_traditional_planet_spacing_ly(planets)
    assert diameter == pytest.approx(200.0)
    area = populated_map_geometric_area_ly2(planets, settings)
    assert area == pytest.approx(math.pi * (100.0**2))


def test_rectangular_map_area_uses_width_height(template_planet, sample_settings) -> None:
    settings = replace(
        sample_settings,
        mapshape=MAP_SHAPE_RECTANGULAR,
        mapwidth=800,
        mapheight=600,
    )
    planets = [
        _planet(template_planet, planet_id=1, x=0, y=0),
        _planet(template_planet, planet_id=2, x=200, y=0),
    ]
    assert populated_map_geometric_area_ly2(planets, settings) == pytest.approx(800.0 * 600.0)


def test_planetoids_excluded_from_spacing_and_density(template_planet, sample_settings) -> None:
    settings = replace(sample_settings, mapshape=MAP_SHAPE_ROUND, mapwidth=4000, mapheight=4000)
    planets = [
        _planet(template_planet, planet_id=1, x=0, y=0),
        _planet(template_planet, planet_id=2, x=100, y=0),
        _planet(template_planet, planet_id=3, x=1000, y=0, debrisdisk=1),
    ]
    assert max_traditional_planet_spacing_ly(planets) == pytest.approx(100.0)
    density = estimate_traditional_planet_density(
        planets,
        settings,
        origins=[CoverageOrigin(x=0, y=0, base_range=10_000)],
        nebulas=(),
        map_center=(50.0, 0.0),
    )
    geometric = math.pi * (50.0**2)
    # Fully observed ⇒ n/geometric with n=2 traditional only.
    assert density == pytest.approx(2.0 / geometric)


def test_fully_observed_annulus_credit_near_zero(template_planet, sample_settings) -> None:
    candidate = _planet(template_planet, planet_id=1, x=0, y=0)
    origins = [CoverageOrigin(x=0, y=0, base_range=10_000)]
    credit = cluster_band_fow_credit(
        candidate,
        density_per_ly2=1e-4,
        origins=origins,
        nebulas=(),
        credit_multiplier=1.0,
    )
    assert credit.very_close == pytest.approx(0.0, abs=1e-9)
    assert credit.close_band == pytest.approx(0.0, abs=1e-9)


def test_partial_unobserved_credit_scales_with_area_and_density(template_planet) -> None:
    candidate = _planet(template_planet, planet_id=1, x=0, y=0)
    # Origin covers only the candidate cell: almost all of both bands unobserved.
    origins = [CoverageOrigin(x=0, y=0, base_range=1)]
    density = 2.0e-4
    credit = cluster_band_fow_credit(
        candidate,
        density_per_ly2=density,
        origins=origins,
        nebulas=(),
        credit_multiplier=1.0,
    )
    very_close_area = unobserved_annulus_area_ly2(
        candidate, r_inner=0.0, r_outer=81.0, origins=origins, nebulas=()
    )
    close_area = unobserved_annulus_area_ly2(
        candidate, r_inner=81.0, r_outer=162.0, origins=origins, nebulas=()
    )
    assert very_close_area > 0.5 * math.pi * (81.0**2)
    assert close_area > 0.5 * math.pi * (162.0**2 - 81.0**2)
    assert credit.very_close == pytest.approx(density * very_close_area)
    assert credit.close_band == pytest.approx(density * close_area)

    doubled = cluster_band_fow_credit(
        candidate,
        density_per_ly2=density,
        origins=origins,
        nebulas=(),
        credit_multiplier=2.0,
    )
    assert doubled.very_close == pytest.approx(2.0 * credit.very_close)
    assert doubled.close_band == pytest.approx(2.0 * credit.close_band)


def test_credit_cap_prevents_over_satisfaction(sample_settings) -> None:
    known = ClusterNeighborCounts(very_close=1, close_band=0)
    settings = replace(sample_settings, verycloseplanets=2, closeplanets=3)
    raw_credit = ClusterFowBandCredit(very_close=10.0, close_band=10.0)
    capped = capped_cluster_fow_credit(known, raw_credit, settings)
    assert capped.very_close == pytest.approx(1.0)
    assert capped.close_band == pytest.approx(3.0)
    assert meets_homeworld_cluster_constraint_with_credit(known, raw_credit, settings)
    assert cluster_constraint_deficit_with_credit(known, raw_credit, settings) == 0


def test_known_neighbors_not_double_counted_with_credit(template_planet, sample_settings) -> None:
    """Observed known planets raise known counts; FoW credit only fills remaining deficit."""
    candidate = _planet(template_planet, planet_id=1, x=0, y=0)
    neighbor = _planet(template_planet, planet_id=2, x=50, y=0)
    known = count_cluster_neighbors(candidate, [candidate, neighbor])
    assert known.very_close == 1
    assert known.close_band == 0
    settings = replace(sample_settings, verycloseplanets=2, closeplanets=0)
    # Fully observed ⇒ zero credit; still short one very-close neighbor.
    credit = cluster_band_fow_credit(
        candidate,
        density_per_ly2=1.0,
        origins=[CoverageOrigin(x=0, y=0, base_range=10_000)],
        nebulas=(),
    )
    assert credit.very_close == pytest.approx(0.0, abs=1e-9)
    assert not meets_homeworld_cluster_constraint_with_credit(known, credit, settings)


def test_p40_class_close_band_regains_candidacy_with_fow_credit(
    template_planet, sample_settings
) -> None:
    """680224-class narrative: known close-band shortfall can be filled by FoW credit.

    Accept: when close-band unobserved area × density covers the remaining
    ``closeplanets`` deficit, the site meets the hard cluster gate.
    """
    candidate = _planet(template_planet, planet_id=40, x=0, y=0)
    # One known close-band neighbor; settings require 4 close -- shortfall of 3.
    known_neighbor = _planet(template_planet, planet_id=41, x=100, y=0)
    known = count_cluster_neighbors(candidate, [candidate, known_neighbor])
    assert known.close_band == 1
    settings = replace(sample_settings, verycloseplanets=0, closeplanets=4)
    # Tiny scan reach ⇒ large unobserved close annulus; density high enough to fill.
    origins = [CoverageOrigin(x=0, y=0, base_range=1)]
    density = 1.0e-3
    credit = cluster_band_fow_credit(
        candidate,
        density_per_ly2=density,
        origins=origins,
        nebulas=(),
        credit_multiplier=1.0,
    )
    assert credit.close_band >= 3.0
    assert meets_homeworld_cluster_constraint_with_credit(known, credit, settings)


def test_nebula_increases_unobserved_annulus_area(template_planet) -> None:
    candidate = _planet(template_planet, planet_id=1, x=0, y=0)
    # Ideal disk covers most of the very-close band; dense nebula shrinks V(P).
    origins = [CoverageOrigin(x=0, y=0, base_range=81)]
    clear = unobserved_annulus_area_ly2(
        candidate, r_inner=0.0, r_outer=81.0, origins=origins, nebulas=()
    )
    fog = Nebula(id=1, x=0, y=0, name="Fog", radius=100, intensity=200)
    obscured = unobserved_annulus_area_ly2(
        candidate, r_inner=0.0, r_outer=81.0, origins=origins, nebulas=[fog]
    )
    assert obscured > clear
