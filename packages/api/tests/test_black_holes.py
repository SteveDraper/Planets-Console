"""Golden vectors: ``api.concepts.stellar_cartography.black_holes`` vs fixture."""

import json
from pathlib import Path

import pytest
from api.concepts.stellar_cartography.black_holes import (
    BLACK_HOLE_HALO_EXTRA_LY,
    ERGOSPHERE_BAND_COUNT,
    black_hole_band_at,
    black_hole_fuel_saving_percent_at,
    black_hole_max_warp_at,
    ergosphere_outer_radius,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / "test-fixtures" / "black-hole-ergosphere-contract.json"


@pytest.fixture(scope="module")
def contract_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


class TestBlackHoleErgosphereContract:
    def test_constants_match_fixture(self, contract_fixture):
        assert ERGOSPHERE_BAND_COUNT == contract_fixture["ergosphereBandCount"]
        assert BLACK_HOLE_HALO_EXTRA_LY == contract_fixture["haloExtraLy"]

    def test_geometry_radii(self, contract_fixture):
        halo_extra = contract_fixture["haloExtraLy"]
        for case in contract_fixture["cases"]:
            assert (
                ergosphere_outer_radius(case["coreradius"], case["bandradius"])
                == case["outerRadiusLy"]
            ), case["id"]
            assert case["outerRadiusLy"] + halo_extra == case["haloRadiusLy"], case["id"]

    def test_band_max_warp_and_fuel_saving(self, contract_fixture):
        for case in contract_fixture["cases"]:
            cr = case["coreradius"]
            br = case["bandradius"]
            for sample in case["samples"]:
                dist = sample["dist"]
                assert black_hole_band_at(cr, br, dist) == sample["band"], case["id"]
                assert black_hole_max_warp_at(cr, br, dist) == sample["maxWarp"], case["id"]
                assert (
                    black_hole_fuel_saving_percent_at(cr, br, dist) == sample["fuelSavingPercent"]
                ), case["id"]
