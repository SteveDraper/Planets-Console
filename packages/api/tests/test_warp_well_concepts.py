"""Unit tests for ``api.concepts.warp_well``."""

import json
from pathlib import Path

import pytest
from api.concepts.warp_well import (
    NORMAL_WELL_CELL_COUNT,
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
    min_distance_to_reachability_well,
    planet_is_in_debris_disk,
    point_in_reachability_well,
    warp_well_cartesian_distance,
)
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def lorthidonia_planet():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    _, turns, _, _, _, _ = build_service_stack(backend)
    return turns.get_planet_from_turn(628580, 1, 111, 1)


class TestPlanetIsInDebrisDisk:
    def test_zero_is_false(self, lorthidonia_planet):
        assert lorthidonia_planet.debrisdisk == 0
        assert planet_is_in_debris_disk(lorthidonia_planet) is False

    def test_nonzero_is_true(self, lorthidonia_planet):
        from dataclasses import replace

        p = replace(lorthidonia_planet, debrisdisk=1)
        assert planet_is_in_debris_disk(p) is True


class TestCoordinateInWarpWell:
    def test_planet_cell_center_inside_normal(self, lorthidonia_planet):
        px, py = lorthidonia_planet.x, lorthidonia_planet.y
        assert coordinate_in_warp_well(
            lorthidonia_planet, float(px), float(py), WarpWellKind.NORMAL
        )

    def test_distance_three_on_boundary_normal(self, lorthidonia_planet):
        px, py = lorthidonia_planet.x, lorthidonia_planet.y
        assert coordinate_in_warp_well(
            lorthidonia_planet, float(px + 3), float(py), WarpWellKind.NORMAL
        )

    def test_distance_three_outside_hyperjump(self, lorthidonia_planet):
        px, py = lorthidonia_planet.x, lorthidonia_planet.y
        assert not coordinate_in_warp_well(
            lorthidonia_planet, float(px + 3), float(py), WarpWellKind.HYPERJUMP
        )

    def test_debris_disk_always_false(self, lorthidonia_planet):
        from dataclasses import replace

        p = replace(lorthidonia_planet, debrisdisk=1)
        assert not coordinate_in_warp_well(p, float(p.x), float(p.y), WarpWellKind.NORMAL)


class TestMapCellIndices:
    def test_includes_planet_cell(self, lorthidonia_planet):
        px, py = lorthidonia_planet.x, lorthidonia_planet.y
        cells = map_cell_indices_in_warp_well(lorthidonia_planet, WarpWellKind.NORMAL)
        assert (px, py) in cells

    def test_normal_well_has_fixed_cell_count(self, lorthidonia_planet):
        cells = map_cell_indices_in_warp_well(lorthidonia_planet, WarpWellKind.NORMAL)
        assert len(cells) == NORMAL_WELL_CELL_COUNT

    def test_debris_empty(self, lorthidonia_planet):
        from dataclasses import replace

        p = replace(lorthidonia_planet, debrisdisk=2)
        assert map_cell_indices_in_warp_well(p, WarpWellKind.NORMAL) == []


class TestWarpWellCartesianDistance:
    def test_hypot(self):
        assert warp_well_cartesian_distance(0, 0, 3, 4) == 5.0


class TestReachabilityWellEquivalence:
    def test_point_in_matches_canonical_for_non_debris(self, lorthidonia_planet):
        cases = [
            (float(lorthidonia_planet.x), float(lorthidonia_planet.y)),
            (float(lorthidonia_planet.x) + 3, float(lorthidonia_planet.y)),
            (float(lorthidonia_planet.x) + 4, float(lorthidonia_planet.y)),
        ]
        for qx, qy in cases:
            canonical = coordinate_in_warp_well(lorthidonia_planet, qx, qy, WarpWellKind.NORMAL)
            reachability = point_in_reachability_well(lorthidonia_planet, qx, qy)
            assert reachability == canonical

    def test_min_distance_zero_inside_disc(self, lorthidonia_planet):
        px, py = float(lorthidonia_planet.x), float(lorthidonia_planet.y)
        assert min_distance_to_reachability_well(px + 2, py, lorthidonia_planet) == 0.0

    def test_min_distance_outside_disc(self, lorthidonia_planet):
        from dataclasses import replace

        p = replace(lorthidonia_planet, x=0, y=0)
        assert min_distance_to_reachability_well(10.0, 0.0, p) == 7.0
