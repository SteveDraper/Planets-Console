"""Tests for planet travel connection routes (warp wells, optional flares, spatial index)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.concepts.planet_connections import (
    FlareConnectionMode,
    _PlanetSpatialIndex,
    connection_routes_for_planets,
    max_travel_distance,
    min_distance_point_to_simplified_normal_well,
)
from api.services.game_service import GameService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_planet():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    svc = GameService(backend)
    return svc.get_planet_from_turn(628580, 1, 111, 1)


def _p(base, pid: int, x: int, y: int, debris: int = 0):
    return replace(base, id=pid, x=x, y=y, debrisdisk=debris)


class TestMaxTravelDistance:
    def test_warp_squared(self):
        assert max_travel_distance(3, False) == 9.0
        assert max_travel_distance(9, False) == 81.0

    def test_gravitonic_doubles(self):
        assert max_travel_distance(9, True) == 162.0


class TestMinDistanceSimplifiedWell:
    def test_debris_is_point_distance(self, sample_planet):
        debris = _p(sample_planet, 1, 10, 10, debris=1)
        assert min_distance_point_to_simplified_normal_well(10.0, 10.0, debris) == 0.0
        assert min_distance_point_to_simplified_normal_well(11.0, 10.0, debris) == 1.0

    def test_normal_well_shrinks_by_radius(self, sample_planet):
        p = _p(sample_planet, 1, 0, 0, debris=0)
        assert min_distance_point_to_simplified_normal_well(3.0, 0.0, p) == 0.0
        assert min_distance_point_to_simplified_normal_well(10.0, 0.0, p) == 7.0


def _brute_force_direct(a, b, max_travel: float) -> bool:
    ax, ay = float(a.x), float(a.y)
    bx, by = float(b.x), float(b.y)
    return min_distance_point_to_simplified_normal_well(ax, ay, b) <= max_travel + 1e-9 or (
        min_distance_point_to_simplified_normal_well(bx, by, a) <= max_travel + 1e-9
    )


class TestConnectionRoutesBruteForce:
    def test_grid_matches_brute_force_small_set(self, sample_planet):
        planets = [
            _p(sample_planet, 10, 0, 0),
            _p(sample_planet, 20, 2, 0),
            _p(sample_planet, 30, 100, 100),
        ]
        got = connection_routes_for_planets(
            planets,
            warp_speed=9,
            gravitonic_movement=False,
            flare_mode=FlareConnectionMode.OFF,
        )

        max_travel = max_travel_distance(9, False)
        expected: list[dict[str, bool | int]] = []
        ordered = sorted(planets, key=lambda p: p.id)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                if _brute_force_direct(a, b, max_travel):
                    expected.append({"fromPlanetId": a.id, "toPlanetId": b.id, "viaFlare": False})
        assert got == expected

    def test_adjacent_planets_connected_at_warp_one(self, sample_planet):
        a = _p(sample_planet, 1, 0, 0)
        b = _p(sample_planet, 2, 1, 0)
        routes = connection_routes_for_planets(
            [a, b],
            warp_speed=1,
            gravitonic_movement=False,
            flare_mode=FlareConnectionMode.OFF,
        )
        assert routes == [{"fromPlanetId": 1, "toPlanetId": 2, "viaFlare": False}]

    def test_flare_only_omits_direct_only_pairs(self, sample_planet):
        """ONLY mode keeps edges that require a flare; pure direct pairs are dropped."""
        a = _p(sample_planet, 1, 0, 0)
        b = _p(sample_planet, 2, 1, 0)
        off = connection_routes_for_planets(
            [a, b],
            warp_speed=1,
            gravitonic_movement=False,
            flare_mode=FlareConnectionMode.OFF,
        )
        only = connection_routes_for_planets(
            [a, b],
            warp_speed=1,
            gravitonic_movement=False,
            flare_mode=FlareConnectionMode.ONLY,
        )
        assert off == [{"fromPlanetId": 1, "toPlanetId": 2, "viaFlare": False}]
        assert only == []


def test_flare_p5_p6_waypoint_farther_than_warp_squared(sample_planet):
    """Host flare (50,72)->(47,67) at warp 9 has waypoint hypot > 81 but reaches p6's well."""
    p5 = _p(sample_planet, 5, 2479, 1788)
    p6 = _p(sample_planet, 6, 2528, 1857)
    routes = connection_routes_for_planets(
        [p5, p6],
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
    )
    assert routes == [
        {"fromPlanetId": 5, "toPlanetId": 6, "viaFlare": True},
    ]


class TestSpatialIndexFallback:
    def test_fallback_visits_all_points(self, sample_planet):
        pts = [_p(sample_planet, 200 + i, i, 0) for i in range(5)]
        idx = _PlanetSpatialIndex(pts)
        found = {
            p.id
            for p in idx.iter_planets_within_radius(2.0, 0.0, 2.5, min_planet_id_exclusive=None)
        }
        assert found == {200, 201, 202, 203, 204}
