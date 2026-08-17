"""Unit tests for shared stellar-cartography wormhole and debris-disk predicates."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.concepts.stellar_cartography.debris_disks import debris_disk_seed_radius
from api.concepts.stellar_cartography.wormholes import wormhole_has_known_target
from api.models.space import Wormhole
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def sample_planet():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        turn = turn_info_from_json(json.load(f))
    return turn.planets[0]


@pytest.mark.parametrize(
    ("targetx", "targety", "expected"),
    [
        (0, 0, False),
        (0, 1, True),
        (1, 0, True),
        (3125, 2288, True),
    ],
)
def test_wormhole_has_known_target(targetx: int, targety: int, expected: bool):
    wormhole = Wormhole(id=1, x=100, y=200, targetx=targetx, targety=targety)
    assert wormhole_has_known_target(wormhole) is expected


@pytest.mark.parametrize(
    ("debrisdisk", "expected"),
    [
        (0, None),
        (1, None),
        (2, 2),
        (37, 37),
    ],
)
def test_debris_disk_seed_radius(sample_planet, debrisdisk: int, expected: int | None):
    planet = replace(sample_planet, debrisdisk=debrisdisk)
    assert debris_disk_seed_radius(planet) == expected
