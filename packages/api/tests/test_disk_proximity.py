"""Unit tests for Core disk proximity (MCP disk proximity game concept)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.concepts.disk_proximity import (
    INCLUDE_CARTOGRAPHY,
    INCLUDE_PLANETS,
    INCLUDE_SHIPS,
    KIND_BLACK_HOLE,
    KIND_DEBRIS_DISK,
    KIND_ION_STORM,
    KIND_NEBULA,
    KIND_PLANET,
    KIND_SHIP,
    KIND_STAR_CLUSTER,
    KIND_WORMHOLE,
    DiskProximityHit,
    disk_proximity,
)
from api.concepts.stellar_cartography.black_holes import ergosphere_outer_radius
from api.concepts.stellar_cartography.star_clusters import halo_radius_ly
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def stellar_cartography_turn():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        return turn_info_from_json(json.load(f))


def _empty_scene(turn):
    scene = copy.deepcopy(turn)
    scene.planets = []
    scene.ships = []
    scene.ionstorms = []
    scene.nebulas = []
    scene.stars = []
    scene.blackholes = []
    scene.wormholes = []
    scene.minefields = []
    return scene


def _kinds(hits: list[DiskProximityHit]) -> list[str]:
    return [hit.kind for hit in hits]


def test_include_all_returns_ships_planets_and_cartography(stellar_cartography_turn):
    turn = _empty_scene(stellar_cartography_turn)
    turn.ships = [replace(stellar_cartography_turn.ships[0], id=11, x=100, y=100)]
    turn.planets = [replace(stellar_cartography_turn.planets[0], id=22, x=105, y=100, debrisdisk=0)]
    turn.nebulas = [replace(stellar_cartography_turn.nebulas[0], id=33, x=100, y=100, radius=20)]
    turn.minefields = [
        replace(stellar_cartography_turn.minefields[0], id=44, x=100, y=100, radius=80)
    ]

    hits = disk_proximity(turn, 100, 100, 10)

    assert {(hit.kind, hit.id) for hit in hits} == {
        (KIND_SHIP, 11),
        (KIND_PLANET, 22),
        (KIND_NEBULA, 33),
    }
    nebula = next(hit for hit in hits if hit.kind == KIND_NEBULA)
    assert nebula.radius == 20
    assert next(hit for hit in hits if hit.kind == KIND_SHIP).radius is None
    assert next(hit for hit in hits if hit.kind == KIND_PLANET).radius is None


def test_include_subsets_filter_kind_families(stellar_cartography_turn):
    turn = _empty_scene(stellar_cartography_turn)
    turn.ships = [replace(stellar_cartography_turn.ships[0], id=11, x=100, y=100)]
    turn.planets = [replace(stellar_cartography_turn.planets[0], id=22, x=100, y=100, debrisdisk=0)]
    turn.nebulas = [replace(stellar_cartography_turn.nebulas[0], id=33, x=100, y=100, radius=20)]

    ship_hits = disk_proximity(turn, 100, 100, 10, include=[INCLUDE_SHIPS])
    planet_hits = disk_proximity(turn, 100, 100, 10, include=[INCLUDE_PLANETS])
    cartography_hits = disk_proximity(turn, 100, 100, 10, include=[INCLUDE_CARTOGRAPHY])
    ships_and_planets = disk_proximity(turn, 100, 100, 10, include=[INCLUDE_SHIPS, INCLUDE_PLANETS])

    assert _kinds(ship_hits) == [KIND_SHIP]
    assert _kinds(planet_hits) == [KIND_PLANET]
    assert _kinds(cartography_hits) == [KIND_NEBULA]
    assert {(hit.kind, hit.id) for hit in ships_and_planets} == {
        (KIND_SHIP, 11),
        (KIND_PLANET, 22),
    }


def test_empty_disk_returns_no_hits(stellar_cartography_turn):
    turn = _empty_scene(stellar_cartography_turn)
    turn.ships = [replace(stellar_cartography_turn.ships[0], id=11, x=1000, y=1000)]
    turn.planets = [replace(stellar_cartography_turn.planets[0], id=22, x=2000, y=2000)]
    turn.nebulas = [replace(stellar_cartography_turn.nebulas[0], id=33, x=3000, y=3000, radius=5)]

    assert disk_proximity(turn, 0, 0, 10) == []
    assert disk_proximity(turn, 0, 0, 0) == []


def test_minefields_are_excluded_even_when_centered_on_query(stellar_cartography_turn):
    turn = _empty_scene(stellar_cartography_turn)
    turn.minefields = [replace(stellar_cartography_turn.minefields[0], id=44, x=0, y=0, radius=100)]
    turn.ships = [replace(stellar_cartography_turn.ships[0], id=11, x=0, y=0)]

    hits = disk_proximity(turn, 0, 0, 50)

    assert [(hit.kind, hit.id) for hit in hits] == [(KIND_SHIP, 11)]
    assert all(hit.kind != "minefield" for hit in hits)


def test_area_feature_hits_on_disk_overlap_not_center_in_radius(stellar_cartography_turn):
    turn = _empty_scene(stellar_cartography_turn)
    turn.nebulas = [replace(stellar_cartography_turn.nebulas[0], id=33, x=100, y=0, radius=50)]

    overlapping = disk_proximity(turn, 0, 0, 60, include=[INCLUDE_CARTOGRAPHY])
    too_far = disk_proximity(turn, 0, 0, 40, include=[INCLUDE_CARTOGRAPHY])

    assert [(hit.kind, hit.id, hit.radius) for hit in overlapping] == [(KIND_NEBULA, 33, 50.0)]
    assert too_far == []


def test_debris_disk_seed_is_cartography_planetoid_is_not(stellar_cartography_turn):
    turn = _empty_scene(stellar_cartography_turn)
    seed = replace(stellar_cartography_turn.planets[0], id=90, x=0, y=0, debrisdisk=37)
    planetoid = replace(stellar_cartography_turn.planets[0], id=91, x=80, y=0, debrisdisk=1)
    turn.planets = [seed, planetoid]

    hits = disk_proximity(turn, 30, 0, 10)
    by_kind = {(hit.kind, hit.id): hit for hit in hits}

    assert (KIND_DEBRIS_DISK, 90) in by_kind
    assert by_kind[(KIND_DEBRIS_DISK, 90)].radius == 37
    assert (KIND_PLANET, 90) not in by_kind
    assert (KIND_DEBRIS_DISK, 91) not in by_kind
    assert (KIND_PLANET, 91) not in by_kind


def test_cartography_kinds_cover_storms_clusters_holes_and_wormholes(stellar_cartography_turn):
    turn = _empty_scene(stellar_cartography_turn)
    turn.ionstorms = [replace(stellar_cartography_turn.ionstorms[0], id=17, x=0, y=0, radius=10)]
    star = replace(stellar_cartography_turn.stars[0], id=2, x=0, y=0, radius=5, mass=100)
    turn.stars = [star]
    hole = replace(
        stellar_cartography_turn.blackholes[0], id=3, x=0, y=0, coreradius=5, bandradius=1
    )
    turn.blackholes = [hole]
    turn.wormholes = [
        replace(
            stellar_cartography_turn.wormholes[2],
            id=4,
            x=0,
            y=0,
            targetx=80,
            targety=0,
        )
    ]

    hits = disk_proximity(turn, 0, 0, 5, include=[INCLUDE_CARTOGRAPHY])
    by_kind = {hit.kind: hit for hit in hits}

    assert set(by_kind) == {
        KIND_ION_STORM,
        KIND_STAR_CLUSTER,
        KIND_BLACK_HOLE,
        KIND_WORMHOLE,
    }
    assert by_kind[KIND_ION_STORM].radius == 10
    assert by_kind[KIND_STAR_CLUSTER].radius == max(float(star.radius), halo_radius_ly(star.mass))
    assert by_kind[KIND_BLACK_HOLE].radius == float(
        ergosphere_outer_radius(hole.coreradius, hole.bandradius)
    )
    assert by_kind[KIND_WORMHOLE].radius is None
    assert (by_kind[KIND_WORMHOLE].x, by_kind[KIND_WORMHOLE].y) == (0, 0)

    exit_hits = disk_proximity(turn, 80, 0, 1, include=[INCLUDE_CARTOGRAPHY])
    assert [(hit.kind, hit.id, hit.x, hit.y) for hit in exit_hits] == [(KIND_WORMHOLE, 4, 80, 0)]
