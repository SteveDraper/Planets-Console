"""Tests for Stellar Cartography Core analytic."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics import TurnAnalyticsOptions, get_turn_analytic
from api.analytics.stellar_cartography import (
    ANALYTIC_ID,
    get_stellar_cartography_map,
    ion_storm_class,
)
from api.concepts.stellar_cartography.star_clusters import (
    neutron_cluster_names,
    stars_grouped_by_name,
)
from api.models.space import Star
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
TURN_49_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / ".data"
    / "games"
    / "673864"
    / "0"
    / "turns"
    / "49.json"
)


@pytest.fixture
def stellar_cartography_turn():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        return turn_info_from_json(json.load(f))


@pytest.fixture
def empty_spatial_turn(stellar_cartography_turn):
    turn = copy.deepcopy(stellar_cartography_turn)
    turn.nebulas = []
    turn.ionstorms = []
    turn.stars = []
    turn.blackholes = []
    turn.wormholes = []
    return turn


def test_ion_storm_class_boundaries():
    assert ion_storm_class(0) == 1
    assert ion_storm_class(49) == 1
    assert ion_storm_class(50) == 2
    assert ion_storm_class(99) == 2
    assert ion_storm_class(100) == 3
    assert ion_storm_class(149) == 3
    assert ion_storm_class(150) == 4
    assert ion_storm_class(199) == 4
    assert ion_storm_class(200) == 5
    assert ion_storm_class(300) == 5


def test_empty_turn_returns_empty_geometry(empty_spatial_turn):
    data = get_stellar_cartography_map(empty_spatial_turn, TurnAnalyticsOptions())
    assert data["analyticId"] == ANALYTIC_ID
    assert data["overlayCircles"] == []
    assert data["nodes"] == []
    assert data["edges"] == []
    assert data["meta"] == {
        "debrisDisks": 0,
        "nebulae": 0,
        "ionStorms": 0,
        "nuIonStorms": True,
        "starClusters": 0,
        "neutronClusters": 0,
        "blackHoles": 0,
        "wormholes": 0,
        "wormholeEdges": 0,
    }


def test_debris_disk_overlay_from_seed_planet(stellar_cartography_turn):
    turn = copy.deepcopy(stellar_cartography_turn)
    seed = replace(turn.planets[0], id=900, name="Boring Planet - 1", x=2803, y=1526, debrisdisk=37)
    turn.planets = [seed, *turn.planets[1:]]
    data = get_stellar_cartography_map(turn, TurnAnalyticsOptions())
    debris = [c for c in data["overlayCircles"] if c["layer"] == "debris-disks"]
    assert len(debris) == 1
    assert debris[0] == {
        "layer": "debris-disks",
        "id": "dd-900",
        "x": 2803,
        "y": 1526,
        "radius": 37,
        "name": "Boring Planet - 1",
        "planetId": 900,
    }
    assert data["meta"]["debrisDisks"] == 1


def test_planetoid_does_not_emit_debris_disk_overlay(stellar_cartography_turn):
    turn = copy.deepcopy(stellar_cartography_turn)
    planetoid = replace(turn.planets[0], id=901, debrisdisk=1)
    turn.planets = [planetoid, *turn.planets[1:]]
    data = get_stellar_cartography_map(turn, TurnAnalyticsOptions())
    assert [c for c in data["overlayCircles"] if c["layer"] == "debris-disks"] == []
    assert data["meta"]["debrisDisks"] == 0


def test_overlay_circle_counts(stellar_cartography_turn):
    data = get_stellar_cartography_map(stellar_cartography_turn, TurnAnalyticsOptions())
    layers = [c["layer"] for c in data["overlayCircles"]]
    assert layers.count("nebulae") == 1
    assert layers.count("ion-storms") == len(stellar_cartography_turn.ionstorms)
    assert layers.count("star-clusters") == len(stellar_cartography_turn.stars)
    assert layers.count("neutron-clusters") == 0
    assert layers.count("black-holes") == 1
    clusters_by_name = stars_grouped_by_name(stellar_cartography_turn.stars)
    neutron_names = neutron_cluster_names(stellar_cartography_turn.stars)
    assert data["meta"]["starClusters"] == len(clusters_by_name) - len(neutron_names)
    assert data["meta"]["neutronClusters"] == len(neutron_names)


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


def test_meta_cluster_counts_use_distinct_names_not_bodies(stellar_cartography_turn):
    """Meta starClusters/neutronClusters count cluster names, not star bodies."""
    turn = copy.deepcopy(stellar_cartography_turn)
    turn.stars = [
        _star(id=1, name="Bith", x=10, y=10, radius=5),
        _star(id=2, name="Bith", x=12, y=11, radius=5),
        _star(id=3, name="Fortuitous", x=50, y=50, radius=40),
        _star(id=4, name="SoloNeutron", x=60, y=60, radius=7),
        _star(id=5, name="WideRadiation", x=70, y=70, radius=40),
        _star(id=6, name="WideRadiation", x=71, y=71, radius=41),
        _star(id=7, name="Mixed", x=80, y=80, radius=5),
        _star(id=8, name="Mixed", x=81, y=81, radius=40),
    ]
    data = get_stellar_cartography_map(turn, TurnAnalyticsOptions())
    assert len(turn.stars) == 8
    assert data["meta"]["neutronClusters"] == 3
    assert data["meta"]["starClusters"] == 2


def test_nebula_and_blackhole_overlay_fields(stellar_cartography_turn):
    data = get_stellar_cartography_map(stellar_cartography_turn, TurnAnalyticsOptions())
    nebula = next(c for c in data["overlayCircles"] if c["layer"] == "nebulae")
    assert nebula == {
        "layer": "nebulae",
        "id": "neb-1",
        "x": 100,
        "y": 200,
        "radius": 50,
        "name": "Zoie",
        "intensity": 6,
        "gas": 3,
    }
    blackhole = next(c for c in data["overlayCircles"] if c["layer"] == "black-holes")
    assert blackhole["coreRadius"] == 15
    assert blackhole["bandRadius"] == 4
    assert blackhole["radius"] == 51


def test_ion_storm_overlay_includes_class(stellar_cartography_turn):
    data = get_stellar_cartography_map(stellar_cartography_turn, TurnAnalyticsOptions())
    storm = next(c for c in data["overlayCircles"] if c["id"] == "is-17")
    assert storm["class"] == ion_storm_class(storm["voltage"])
    assert storm["parentId"] == 0


def test_wormhole_bidirectional_dedupes_to_one_edge(stellar_cartography_turn):
    data = get_stellar_cartography_map(stellar_cartography_turn, TurnAnalyticsOptions())
    bidirectional = [e for e in data["edges"] if e.get("isBidirectional")]
    assert len(bidirectional) == 1
    assert bidirectional[0]["source"] == "wh-1"
    assert bidirectional[0]["target"] == "wh-2"
    assert bidirectional[0]["partnerId"] == 2


def test_wormhole_mono_directional_adds_exit_node(stellar_cartography_turn):
    data = get_stellar_cartography_map(stellar_cartography_turn, TurnAnalyticsOptions())
    mono = next(e for e in data["edges"] if not e["isBidirectional"])
    assert mono["source"] == "wh-3"
    assert mono["target"] == "wh-exit-3"
    exit_node = next(n for n in data["nodes"] if n["id"] == "wh-exit-3")
    assert exit_node["x"] == 40
    assert exit_node["y"] == 40


def test_registry_dispatches_stellar_cartography(stellar_cartography_turn):
    data = get_turn_analytic(ANALYTIC_ID, stellar_cartography_turn, TurnAnalyticsOptions())
    assert data["analyticId"] == ANALYTIC_ID
    assert len(data["overlayCircles"]) > 0


@pytest.mark.skipif(not TURN_49_PATH.is_file(), reason="local fixture game 673864 turn 49")
def test_turn_49_wormhole_edge_dedupe_matches_host():
    with open(TURN_49_PATH) as f:
        turn = turn_info_from_json(json.load(f))
    data = get_stellar_cartography_map(turn, TurnAnalyticsOptions())
    assert len(turn.wormholes) == 112
    assert data["meta"]["wormholeEdges"] == 56
    assert len(data["nodes"]) == 112
