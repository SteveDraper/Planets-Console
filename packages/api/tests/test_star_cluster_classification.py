"""Tests for neutron vs radiation star cluster classification."""

import json
from copy import deepcopy
from pathlib import Path

from api.concepts.stellar_cartography.layers import LAYER_NEUTRON_CLUSTERS, LAYER_STAR_CLUSTERS
from api.concepts.stellar_cartography.sample_at import sample_at
from api.concepts.stellar_cartography.star_clusters import (
    cluster_neutron_kind,
    format_neutrino_movement_bonus,
    format_neutrino_warp_9_max_range,
    is_neutron_star_body,
    neutrino_max_range_at_warp_9,
    neutrino_movement_bonus_fraction,
    neutrino_movement_bonus_percent,
    neutron_cluster_names,
    star_cluster_layer,
)
from api.models.space import Star
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _star(**kwargs) -> Star:
    defaults = {
        "id": 1,
        "name": "Solo",
        "x": 100,
        "y": 200,
        "temp": 10_000,
        "radius": 5,
        "mass": 10_000,
        "planets": 0,
    }
    defaults.update(kwargs)
    return Star(**defaults)


def test_is_neutron_star_body_by_core_radius():
    assert is_neutron_star_body(_star(radius=5))
    assert is_neutron_star_body(_star(radius=10))
    assert not is_neutron_star_body(_star(radius=4))
    assert not is_neutron_star_body(_star(radius=11))
    assert not is_neutron_star_body(_star(radius=40))


def test_cluster_neutron_kind_from_constituent_radii():
    assert cluster_neutron_kind([_star(radius=5)]) == "neutron"
    assert cluster_neutron_kind([_star(radius=40)]) == "radiation"
    assert cluster_neutron_kind([_star(radius=5), _star(id=2, radius=10)]) == "neutron"
    assert cluster_neutron_kind([_star(radius=40), _star(id=2, radius=45)]) == "radiation"
    assert cluster_neutron_kind([_star(radius=5), _star(id=2, radius=40)]) == "ambiguous_mixed"


def test_neutron_cluster_names_from_core_radius_not_body_count():
    stars = [
        _star(id=1, name="Bith", x=10, y=10, radius=5),
        _star(id=2, name="Bith", x=12, y=11, radius=5),
        _star(id=3, name="Fortuitous", x=50, y=50, radius=40),
        _star(id=4, name="SoloNeutron", x=60, y=60, radius=7),
        _star(id=5, name="WideRadiation", x=70, y=70, radius=40),
        _star(id=6, name="WideRadiation", x=71, y=71, radius=41),
        _star(id=7, name="Mixed", x=80, y=80, radius=5),
        _star(id=8, name="Mixed", x=81, y=81, radius=40),
    ]
    neutron_names = neutron_cluster_names(stars)
    assert neutron_names == {"Bith", "SoloNeutron", "Mixed"}
    assert star_cluster_layer("Bith", neutron_names) == LAYER_NEUTRON_CLUSTERS
    assert star_cluster_layer("Fortuitous", neutron_names) == LAYER_STAR_CLUSTERS
    assert star_cluster_layer("WideRadiation", neutron_names) == LAYER_STAR_CLUSTERS
    assert star_cluster_layer("Mixed", neutron_names) == LAYER_NEUTRON_CLUSTERS


def test_neutrino_movement_bonus_matches_planets_client():
    assert neutrino_movement_bonus_fraction(0) == 0.0
    assert neutrino_movement_bonus_fraction(42) == 0.042
    assert neutrino_movement_bonus_fraction(250) == 0.25
    assert neutrino_movement_bonus_fraction(300) == 0.3
    assert neutrino_movement_bonus_fraction(420) == 0.3
    assert neutrino_movement_bonus_percent(42) == 4.2
    assert neutrino_movement_bonus_percent(250) == 25.0
    assert format_neutrino_movement_bonus(42) == "+4.2%"
    assert format_neutrino_movement_bonus(250) == "+25%"
    assert format_neutrino_movement_bonus(300) == "+30%"
    assert format_neutrino_movement_bonus(420) == "+30%"
    assert neutrino_max_range_at_warp_9(0) == 81.0
    assert neutrino_max_range_at_warp_9(42) == 84.402
    assert neutrino_max_range_at_warp_9(300) == 105.3
    assert format_neutrino_warp_9_max_range(42) == "84.4 ly at warp 9"
    assert format_neutrino_warp_9_max_range(300) == "105.3 ly at warp 9"


def test_neutrino_flux_sums_bodies_and_lethal_lines_per_core():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        turn = turn_info_from_json(json.load(f))
    turn.stars = [
        _star(id=1, name="Bith", x=100, y=100, temp=10_000, radius=5, mass=10_000),
        _star(id=2, name="Bith", x=103, y=100, temp=10_000, radius=5, mass=10_000),
    ]

    data = sample_at(turn, 100 + 5 + 10, 100)
    neutron = [entry for entry in data["entries"] if entry["layer"] == LAYER_NEUTRON_CLUSTERS]
    assert len(neutron) == 1
    flux_line = neutron[0]["lines"][0]
    assert flux_line.startswith("Bith — neutrino flux ")
    assert " — movement +" in flux_line
    flux = int(flux_line.split("neutrino flux ", 1)[1].split(" — movement ", 1)[0])
    bonus = format_neutrino_movement_bonus(flux)
    warp_9 = format_neutrino_warp_9_max_range(flux)
    assert flux_line.endswith(f" — movement {bonus} ({warp_9})")

    single_core_turn = deepcopy(turn)
    single_core_turn.stars = [
        _star(id=1, name="Bith", x=100, y=100, temp=10_000, radius=5, mass=10_000),
        _star(id=2, name="Bith", x=200, y=200, temp=10_000, radius=5, mass=10_000),
    ]
    core_data = sample_at(single_core_turn, 100, 100)
    lethal = [
        entry
        for entry in core_data["entries"]
        if entry["layer"] == LAYER_NEUTRON_CLUSTERS and "lethal" in entry["lines"][0]
    ]
    assert len(lethal) == 1
    assert lethal[0]["lines"][0] == "Bith — lethal — temp 10000"

    overlap_data = sample_at(turn, 101, 100)
    overlap_lethal = [
        entry
        for entry in overlap_data["entries"]
        if entry["layer"] == LAYER_NEUTRON_CLUSTERS and "lethal" in entry["lines"][0]
    ]
    assert len(overlap_lethal) == 2
