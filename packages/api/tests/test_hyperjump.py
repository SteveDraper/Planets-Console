"""Tests for hyperjump activation and landing estimate."""

from __future__ import annotations

from dataclasses import replace

from api.concepts.hyperjump import (
    friendly_code_is_hyp,
    hyperjump_landing_xy,
    ship_is_performing_hyperjump,
)
from api.models.components import Hull


def _hull(*, special: str) -> Hull:
    return Hull(
        id=87,
        name="Falcon Class Escort",
        tritanium=1,
        duranium=1,
        molybdenum=1,
        fueltank=100,
        crew=10,
        engines=1,
        mass=10,
        techlevel=1,
        cargo=10,
        fighterbays=0,
        launchers=0,
        beams=2,
        cancloak=False,
        cost=10,
        special=special,
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def test_friendly_code_is_hyp_case_insensitive():
    assert friendly_code_is_hyp("HYP")
    assert friendly_code_is_hyp("hyp")
    assert friendly_code_is_hyp("HyP")
    assert not friendly_code_is_hyp("HYP ")
    assert not friendly_code_is_hyp("xyz")


def test_ship_is_performing_hyperjump_requires_hull_fc_warp_fuel_range(sample_turn):
    ship = replace(
        sample_turn.ships[0],
        friendlycode="HYp",
        warp=7,
        neutronium=50,
        x=1000,
        y=1000,
        targetx=1000 + 300,
        targety=1000,
    )
    hyp_hull = _hull(special="Hyperjump - Can jump 350 ly")
    assert ship_is_performing_hyperjump(ship, hyp_hull)

    assert not ship_is_performing_hyperjump(ship, None)
    assert not ship_is_performing_hyperjump(ship, _hull(special="Gravitonic"))
    assert not ship_is_performing_hyperjump(replace(ship, friendlycode="abc"), hyp_hull)
    assert not ship_is_performing_hyperjump(replace(ship, warp=0), hyp_hull)
    assert not ship_is_performing_hyperjump(replace(ship, neutronium=49), hyp_hull)
    assert not ship_is_performing_hyperjump(
        replace(ship, targetx=ship.x + 10, targety=ship.y),
        hyp_hull,
    )


def test_hyperjump_landing_fine_tunes_within_340_360(sample_turn):
    ship = replace(
        sample_turn.ships[0],
        x=2458,
        y=2128,
        targetx=2311,
        targety=2441,
    )
    assert hyperjump_landing_xy(ship) == (2311, 2441)


def test_hyperjump_landing_flat_350_outside_fine_tune_band(sample_turn):
    ship = replace(
        sample_turn.ships[0],
        x=1000,
        y=2000,
        targetx=1000 + 100,
        targety=2000,
    )
    assert hyperjump_landing_xy(ship) == (1350, 2000)
