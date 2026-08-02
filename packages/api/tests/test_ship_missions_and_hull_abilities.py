"""Tests for ship mission and hull ability helpers."""

from api.concepts.hull_abilities import (
    hull_has_bioscan,
    hull_has_gravitonic_movement,
    hull_has_hyperjump,
    hull_has_nebula_scanner,
)
from api.concepts.ship_missions import (
    MINE_SWEEP_MISSION,
    SENSOR_SWEEP_MISSION,
    is_mine_sweep_mission,
    is_sensor_sweep_or_bioscan_mission,
)
from api.models.components import Hull


def _hull(*, hull_id: int = 1, name: str = "Scout", special: str = "") -> Hull:
    return Hull(
        id=hull_id,
        name=name,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        fueltank=0,
        crew=0,
        engines=1,
        mass=0,
        techlevel=1,
        cargo=0,
        fighterbays=0,
        launchers=0,
        beams=0,
        cancloak=False,
        cost=0,
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


def test_sensor_sweep_mission_id():
    assert SENSOR_SWEEP_MISSION == 4
    assert is_sensor_sweep_or_bioscan_mission(4)
    assert not is_sensor_sweep_or_bioscan_mission(0)
    assert not is_sensor_sweep_or_bioscan_mission(6)


def test_mine_sweep_mission_id():
    assert MINE_SWEEP_MISSION == 1
    assert is_mine_sweep_mission(1)
    assert not is_mine_sweep_mission(4)
    assert not is_mine_sweep_mission(0)


def test_hull_has_bioscan_from_special():
    assert hull_has_bioscan(_hull(special="Bioscan - Will detect 20% of all native life"))
    advanced = "Advanced Bioscan - Will detect 100% of all native life when Sensor Sweeping."
    assert hull_has_bioscan(_hull(special=advanced))
    assert not hull_has_bioscan(_hull(special="Gravitonic"))


def test_hull_has_gravitonic_movement_from_special():
    gravitonic = "Gravitonic - This ship moves twice as far as normal ships."
    assert hull_has_gravitonic_movement(_hull(special=gravitonic))
    assert not hull_has_gravitonic_movement(_hull(special="Bioscan - Will detect"))


def test_hull_has_nebula_scanner_from_special():
    special = "Nebula Scanner - Can detect ships or planets within a nebula"
    assert hull_has_nebula_scanner(_hull(special=special))
    assert not hull_has_nebula_scanner(_hull(special="Bioscan - Will detect"))


def test_hull_has_hyperjump_from_special():
    assert hull_has_hyperjump(_hull(special="Hyperjump - Can jump 350 ly with FC HYP"))
    assert hull_has_hyperjump(_hull(special="Hyperdrive capable escort"))
    assert not hull_has_hyperjump(_hull(special="Gravitonic - moves twice as far"))
