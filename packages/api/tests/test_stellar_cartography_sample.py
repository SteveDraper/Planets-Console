"""Tests for Stellar Cartography ``sample_at`` concept."""

import json
import math
from pathlib import Path

import pytest
from api.concepts.stellar_cartography.sample_at import (
    NEBULA_VISIBILITY_MAX_LY,
    sample_at,
)
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def stellar_cartography_turn():
    with open(ASSETS_DIR / "turn_stellar_cartography_sample.json") as f:
        return turn_info_from_json(json.load(f))


def _entries_by_layer(data: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for entry in data["entries"]:
        out.setdefault(entry["layer"], []).append(entry)
    return out


def test_nebula_name_at_center(stellar_cartography_turn):
    nebula = stellar_cartography_turn.nebulas[0]
    data = sample_at(stellar_cartography_turn, nebula.x, nebula.y)
    nebulae = _entries_by_layer(data)["nebulae"]
    assert len(nebulae) == 1
    density = math.ceil(nebula.intensity * (1.0 - 0 / nebula.radius))
    visibility = min(NEBULA_VISIBILITY_MAX_LY, round(4000 / (density + 1)))
    assert nebulae[0]["lines"] == [nebula.name, f"{visibility} ly"]


def test_nebula_visibility_can_exceed_hundred_ly():
    from api.concepts.stellar_cartography.sample_at import _nebula_visibility_ly

    assert _nebula_visibility_ly(38) == 103
    assert _nebula_visibility_ly(39) == 100


def test_nebula_visibility_capped_at_two_fifty_ly():
    from api.concepts.stellar_cartography.sample_at import _nebula_visibility_ly

    assert _nebula_visibility_ly(1) == 250
    assert _nebula_visibility_ly(15) == 250


def test_nebula_groups_overlapping_centers_by_name(stellar_cartography_turn):
    from copy import deepcopy

    turn = deepcopy(stellar_cartography_turn)
    duplicate = deepcopy(turn.nebulas[0])
    duplicate.id = 99
    duplicate.x = turn.nebulas[0].x + 10
    turn.nebulas.append(duplicate)
    data = sample_at(turn, turn.nebulas[0].x, turn.nebulas[0].y)
    nebulae = _entries_by_layer(data)["nebulae"]
    assert len(nebulae) == 1
    assert nebulae[0]["lines"][0] == turn.nebulas[0].name


def test_cloudy_ion_voltage_sums_subcircles(stellar_cartography_turn):
    turn = stellar_cartography_turn
    assert turn.settings.nuionstorms is True
    parent = next(s for s in turn.ionstorms if s.parentid == 0)
    data = sample_at(turn, parent.x, parent.y)
    ion = _entries_by_layer(data)["ion-storms"]
    assert len(ion) == 1
    assert ion[0]["lines"][0].startswith("Class ")
    assert ion[0]["lines"][1].endswith(" V")


def test_star_cluster_radiation_at_halo(stellar_cartography_turn):
    star = stellar_cartography_turn.stars[0]
    x = star.x + star.radius + 5
    y = star.y
    data = sample_at(stellar_cartography_turn, x, y)
    clusters = _entries_by_layer(data).get("star-clusters", [])
    assert len(clusters) == 1
    assert "radiation" in clusters[0]["lines"][0]


def test_star_cluster_lethal_in_core_includes_temp(stellar_cartography_turn):
    star = stellar_cartography_turn.stars[0]
    data = sample_at(stellar_cartography_turn, star.x, star.y)
    clusters = _entries_by_layer(data)["star-clusters"]
    assert len(clusters) == 1
    assert clusters[0]["lines"] == [f"{star.name} — lethal — temp {star.temp}"]


def test_black_hole_lethal_in_core(stellar_cartography_turn):
    hole = stellar_cartography_turn.blackholes[0]
    data = sample_at(stellar_cartography_turn, hole.x, hole.y)
    holes = _entries_by_layer(data)["black-holes"]
    assert len(holes) == 1
    assert holes[0]["lines"][0].startswith("Lethal")


def test_black_hole_max_warp_in_band(stellar_cartography_turn):
    hole = stellar_cartography_turn.blackholes[0]
    x = hole.x + hole.coreradius + 5
    y = hole.y
    data = sample_at(stellar_cartography_turn, x, y)
    holes = _entries_by_layer(data)["black-holes"]
    assert len(holes) == 1
    assert holes[0]["lines"][0].startswith("Max warp:")


def test_empty_cell_returns_no_entries(stellar_cartography_turn):
    data = sample_at(stellar_cartography_turn, 0, 0)
    assert data["entries"] == []
