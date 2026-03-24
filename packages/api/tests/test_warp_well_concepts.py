"""Unit tests for ``api.concepts.warp_well``."""

import json
from pathlib import Path

import pytest
from api.concepts.warp_well import (
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
    planet_is_in_debris_disk,
    warp_well_cartesian_distance,
)
from api.services.game_service import GameService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def lorthidonia_planet():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    svc = GameService(backend)
    return svc.get_planet_from_turn(628580, 1, 111, 1)


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

    def test_debris_empty(self, lorthidonia_planet):
        from dataclasses import replace

        p = replace(lorthidonia_planet, debrisdisk=2)
        assert map_cell_indices_in_warp_well(p, WarpWellKind.NORMAL) == []


class TestWarpWellCartesianDistance:
    def test_hypot(self):
        assert warp_well_cartesian_distance(0, 0, 3, 4) == 5.0
