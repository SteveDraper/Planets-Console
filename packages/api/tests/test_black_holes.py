"""Tests for black hole ergosphere helpers (Planets.nu client alignment)."""

from api.concepts.stellar_cartography.black_holes import (
    ERGOSPHERE_BAND_COUNT,
    black_hole_band_at,
    black_hole_fuel_saving_percent_at,
    black_hole_max_warp_at,
    ergosphere_outer_radius,
)


def test_ergosphere_outer_radius():
    assert ergosphere_outer_radius(15, 4) == 15 + 9 * 4


def test_band_at_core_lethal():
    assert black_hole_band_at(15, 4, 15) == 0
    assert black_hole_band_at(15, 4, 10) == 0


def test_band_at_outside_ergosphere():
    outer = ergosphere_outer_radius(15, 4)
    assert black_hole_band_at(15, 4, outer + 0.1) is None


def test_band_numbering_inner_to_outer():
    # Solace-shaped: coreradius=15, bandradius=4
    assert black_hole_band_at(15, 4, 16) == 1
    assert black_hole_band_at(15, 4, 19) == 1
    assert black_hole_band_at(15, 4, 20) == 2
    assert black_hole_band_at(15, 4, ergosphere_outer_radius(15, 4)) == ERGOSPHERE_BAND_COUNT


def test_max_warp_equals_band_number():
    assert black_hole_max_warp_at(15, 4, 16) == 1
    assert black_hole_max_warp_at(15, 4, 20) == 2
    assert black_hole_max_warp_at(15, 4, ergosphere_outer_radius(15, 4)) == 9
    assert black_hole_max_warp_at(15, 4, 15) is None


def test_fuel_saving_percent():
    assert black_hole_fuel_saving_percent_at(15, 4, 16) == 9
    assert black_hole_fuel_saving_percent_at(15, 4, 20) == 8
    assert black_hole_fuel_saving_percent_at(15, 4, ergosphere_outer_radius(15, 4)) == 1
    assert black_hole_fuel_saving_percent_at(15, 4, 15) is None
