"""Tests for planet travel connection routes (warp wells, optional flares, spatial index)."""

import json
import math
import random
from dataclasses import replace
from pathlib import Path

import pytest
from api.concepts.planet_connections import (
    FlareConnectionMode,
    _PlanetSpatialIndex,
    _max_flare_arrival_extent,
    _pair_has_direct_connection,
    _reachable_via_flare_limited_depth,
    connection_routes_for_planets,
    max_travel_distance,
    min_distance_point_to_simplified_normal_well,
)
from api.concepts.flare_points import FlareMovementKind, flare_points_for_warp
from api.concepts.warp_well import NORMAL_RADIUS
from api.models.flare_point import FlarePoint
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


def test_depth_two_includes_single_flare_pairs_from_depth_one(sample_planet):
    """Depth N must not drop 1-flare links that appear at depth 1 (per-k normal check, not N only)."""
    p5 = _p(sample_planet, 5, 2479, 1788)
    p6 = _p(sample_planet, 6, 2528, 1857)
    one = connection_routes_for_planets(
        [p5, p6],
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=1,
    )
    two = connection_routes_for_planets(
        [p5, p6],
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=2,
    )
    assert one == two == [
        {"fromPlanetId": 5, "toPlanetId": 6, "viaFlare": True},
    ]


def test_flare_depth_cap_includes_shorter_chains(sample_planet):
    """A pair needing 2 flares is omitted at max-depth 1 and included at 2 (not only at 3)."""
    a = _p(sample_planet, 1, 2549, 1691)
    b = _p(sample_planet, 2, 2507, 1851)
    assert connection_routes_for_planets(
        [a, b],
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=1,
    ) == []
    assert connection_routes_for_planets(
        [a, b],
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=2,
    ) == [
        {"fromPlanetId": 1, "toPlanetId": 2, "viaFlare": True},
    ]


def test_depth_two_flare_not_shown_when_two_normal_moves_suffice(sample_planet):
    """Regression: do not label depth-2 flare if the pair is already in range in 2 normal moves.

    Example: (2654, 1819) and (2581, 1961) at warp 9 — min distance to the other's well is
    under 2× warp², so no edge in *include* mode (not direct, not flare-only).
    """
    a = _p(sample_planet, 1, 2654, 1819)
    b = _p(sample_planet, 2, 2581, 1961)
    routes = connection_routes_for_planets(
        [a, b],
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=2,
    )
    assert routes == []


def test_flare_connection_allows_normal_move_then_flare(sample_planet):
    """At least one flare on the path; intermediate hops may be normal (≤ max_travel)."""
    a = _p(sample_planet, 1, 0, 0)
    b = _p(sample_planet, 2, 12, 0)
    fl = [FlarePoint((0, 0), (2, 0), (0, 0))]
    mt = 10.0
    assert _reachable_via_flare_limited_depth(a, b, fl, 2, [a, b], mt)


def test_flare_limited_depth_two_hops(sample_planet):
    """A pair can require two flares: one (10,0) hop is short of B; two reach B's well."""
    a = _p(sample_planet, 1, 0, 0)
    b = _p(sample_planet, 2, 20, 0)
    hop = FlarePoint((0, 0), (10, 0), (0, 0))
    mt = max_travel_distance(9, False)
    assert not _reachable_via_flare_limited_depth(a, b, [hop], 1, [a, b], mt)
    assert _reachable_via_flare_limited_depth(a, b, [hop], 2, [a, b], mt)
    c = _p(sample_planet, 3, 10, 0)
    assert not _reachable_via_flare_limited_depth(
        a, b, [hop], 2, [a, b, c], mt
    ), "intermediate arrival must not lie in another planet's well"


def test_flare_bfs_distance_prune_matches_unpruned_on_annulus(sample_planet):
    """Triangle-inequality prune must not change outcomes; sample the flare candidate annulus.

    Center–center distance in (max_travel, max scan] for depth 3, i.e. outside the direct
    inner disc but inside the outer reach used by ``connection_routes_for_planets``.
    """
    warp_speed = 9
    gravitonic = False
    max_tr = max_travel_distance(warp_speed, gravitonic)
    fl = flare_points_for_warp(warp_speed, FlareMovementKind.REGULAR)
    hop_max = _max_flare_arrival_extent(fl)
    d_inner = max_tr + 1e-3
    d_outer = 3 * hop_max + NORMAL_RADIUS

    rng = random.Random(42)
    a = _p(sample_planet, 1, 1000, 1000)
    for _ in range(32):
        t = rng.random() * 2 * math.pi
        u = rng.random()
        r0, r1 = d_inner, d_outer
        r = math.sqrt(r0**2 + u * (r1**2 - r0**2))
        bx = a.x + r * math.cos(t)
        by = a.y + r * math.sin(t)
        b = _p(sample_planet, 2, int(round(bx)), int(round(by)))
        for flare_depth in (1, 2, 3):
            on = connection_routes_for_planets(
                [a, b],
                warp_speed=warp_speed,
                gravitonic_movement=gravitonic,
                flare_mode=FlareConnectionMode.INCLUDE,
                flare_depth=flare_depth,
                flare_bfs_use_distance_prune=True,
            )
            off = connection_routes_for_planets(
                [a, b],
                warp_speed=warp_speed,
                gravitonic_movement=gravitonic,
                flare_mode=FlareConnectionMode.INCLUDE,
                flare_depth=flare_depth,
                flare_bfs_use_distance_prune=False,
            )
            assert on == off, (flare_depth, (b.x, b.y), on, off)


def test_depth_two_flare_real_table_row_waypoint_not_arrival(sample_planet):
    """Hand-verified path: A (2549, 1691) to B (2507, 1851) at warp 9.

    The Host aims at the waypoint (2525, 1770), i.e. offset (-24, 79) from A; the table's
    *arrival* is (-24, 78) so the ship is at (2525, 1769). A second table flare (arrival
    (-16, 80)) ends at (2509, 1849), inside B's simplified well, not on B's map cell.

    BFS and ``connection_routes_for_planets`` use ``arrival_offset`` only; this pair should
    still get a depth-2 flare link when no third planet's well contains (2525, 1769).
    """
    a = _p(sample_planet, 1, 2549, 1691)
    b = _p(sample_planet, 2, 2507, 1851)
    fl = flare_points_for_warp(9, FlareMovementKind.REGULAR)
    first = next(f for f in fl if f.waypoint_offset == (-24, 79) and f.arrival_offset == (-24, 78))
    assert first.direct_aim_arrival_offset == (-24, 77)
    ix, iy = a.x + first.arrival_offset[0], a.y + first.arrival_offset[1]
    assert (ix, iy) == (2525, 1769)
    # The vector from intermediate to B's map cell is (-18, 82), which is not a table row;
    # the (only) table flare that ends in B's well from (2525, 1769) is (-16, 80) -> (2509, 1849).
    assert any(
        f.arrival_offset == (-16, 80) and (ix + f.arrival_offset[0], iy + f.arrival_offset[1]) == (2509, 1849)
        for f in fl
    )
    assert not _pair_has_direct_connection(
        a, b, max_travel_distance(9, False)
    )
    assert _reachable_via_flare_limited_depth(
        a, b, fl, 2, [a, b], max_travel_distance(9, False)
    )
    routes = connection_routes_for_planets(
        [a, b],
        warp_speed=9,
        gravitonic_movement=False,
        flare_mode=FlareConnectionMode.INCLUDE,
        flare_depth=2,
    )
    assert routes == [{"fromPlanetId": 1, "toPlanetId": 2, "viaFlare": True}]



class TestSpatialIndexFallback:
    def test_fallback_visits_all_points(self, sample_planet):
        pts = [_p(sample_planet, 200 + i, i, 0) for i in range(5)]
        idx = _PlanetSpatialIndex(pts)
        found = {
            p.id
            for p in idx.iter_planets_within_radius(2.0, 0.0, 2.5, min_planet_id_exclusive=None)
        }
        assert found == {200, 201, 202, 203, 204}
