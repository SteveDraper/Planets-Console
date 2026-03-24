"""Golden vectors: ``api.concepts.warp_well`` vs ``test-fixtures/warp-well-consistency.json``."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.concepts.warp_well import (
    WarpWellKind,
    coordinate_in_warp_well,
    map_cell_indices_in_warp_well,
)
from api.services.game_service import GameService
from api.storage.memory_asset import MemoryAssetBackend

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "test-fixtures" / "warp-well-consistency.json"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def template_planet():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        backend.put("games/628580/info", json.load(f))
    with open(ASSETS_DIR / "turn_sample.json") as f:
        backend.put("games/628580/1/turns/111", json.load(f))
    svc = GameService(backend)
    return svc.get_planet_from_turn(628580, 1, 111, 1)


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


class TestWarpWellFixtureCoordinateCases:
    def test_coordinate_cases(self, template_planet, fixture_data):
        for case in fixture_data["coordinateCases"]:
            p = replace(
                template_planet,
                x=case["planetX"],
                y=case["planetY"],
                debrisdisk=case["debrisdisk"],
            )
            kind = WarpWellKind(case["wellType"])
            got = coordinate_in_warp_well(p, case["queryX"], case["queryY"], kind)
            assert got == case["inside"], case


class TestWarpWellFixtureCellCases:
    def test_cell_cases(self, template_planet, fixture_data):
        for case in fixture_data["cellCases"]:
            p = replace(
                template_planet,
                x=case["planetX"],
                y=case["planetY"],
                debrisdisk=case["debrisdisk"],
            )
            kind = WarpWellKind(case["wellType"])
            got = [list(t) for t in map_cell_indices_in_warp_well(p, kind)]
            assert got == case["cells"], case
