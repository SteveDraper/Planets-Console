"""Tests for homeworld distribution center resolution."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from visualize_homeworld_distributions import (
    DEFAULT_UNIVERSE_CENTER,
    _game_center,
    _homeworld_bbox_center,
    _planet_bbox_center,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "packages" / "api" / "tests" / "fixtures" / "inference_corpus"
DATA_ROOT = REPO_ROOT / ".data"


@pytest.fixture
def fixture_storage_root(tmp_path: Path) -> Path:
    destination = tmp_path / "games" / "628580"
    shutil.copytree(FIXTURES_ROOT / "628580", destination)
    return tmp_path


def test_homeworld_bbox_center_returns_midpoint() -> None:
    center = _homeworld_bbox_center([(1000, 1100), (1200, 900)])
    assert center == (1100.0, 1000.0)


def test_homeworld_bbox_center_returns_none_for_empty_list() -> None:
    assert _homeworld_bbox_center([]) is None


def test_game_center_uses_homeworld_bbox_when_planets_unavailable(
    fixture_storage_root: Path,
) -> None:
    cache: dict[int, tuple[tuple[float, float], str]] = {}
    homeworlds = [(1813, 2810), (2384, 1296)]
    center = _game_center(fixture_storage_root, 628580, homeworlds, cache)
    assert center == (2098.5, 2053.0)
    assert cache[628580][1] == "homeworld_bbox"


def test_game_center_falls_back_to_homeworld_bbox(tmp_path: Path) -> None:
    cache: dict[int, tuple[tuple[float, float], str]] = {}
    homeworlds = [(1000, 1100), (1200, 900)]
    center = _game_center(tmp_path, 999, homeworlds, cache)
    assert center == (1100.0, 1000.0)
    assert cache[999][1] == "homeworld_bbox"


def test_game_center_falls_back_to_fixed_universe_center(tmp_path: Path) -> None:
    cache: dict[int, tuple[tuple[float, float], str]] = {}
    center = _game_center(tmp_path, 999, [], cache)
    assert center == DEFAULT_UNIVERSE_CENTER
    assert cache[999][1] == "fixed_2000"


@pytest.mark.skipif(not DATA_ROOT.is_dir(), reason="local .data store only")
def test_planet_bbox_center_near_two_thousand_for_local_epic_game() -> None:
    center = _planet_bbox_center(DATA_ROOT, 628580)
    assert center is not None
    assert abs(center[0] - 2000) < 50
    assert abs(center[1] - 2000) < 50


@pytest.mark.skipif(not DATA_ROOT.is_dir(), reason="local .data store only")
def test_game_center_prefers_planet_bbox_for_local_epic_game() -> None:
    cache: dict[int, tuple[tuple[float, float], str]] = {}
    homeworlds = [(1813, 2810)]
    center = _game_center(DATA_ROOT, 628580, homeworlds, cache)
    planet_center = _planet_bbox_center(DATA_ROOT, 628580)
    assert planet_center is not None
    assert center == planet_center
    assert cache[628580][1] == "planet_bbox"


def test_planet_bbox_center_unions_planets_across_perspectives(
    fixture_storage_root: Path,
    tmp_path: Path,
) -> None:
    game_id = 9001
    source = fixture_storage_root / "games" / "628580"
    game_dir = tmp_path / "games" / str(game_id)
    shutil.copytree(source, game_dir)

    turn_one = json.loads((game_dir / "1" / "turns" / "1.json").read_text())
    turn_two = json.loads(json.dumps(turn_one))
    template_planet = json.loads(json.dumps(turn_one["planets"][0]))
    far = json.loads(json.dumps(template_planet))
    far.update({"id": 9001, "x": 3000, "y": 3000, "name": "Far"})
    north = json.loads(json.dumps(template_planet))
    north.update({"id": 9002, "x": 1000, "y": 3000, "name": "North"})
    turn_two["planets"] = [far, north]
    turn_two_dir = game_dir / "2" / "turns"
    turn_two_dir.mkdir(parents=True)
    turn_two_dir.joinpath("1.json").write_text(json.dumps(turn_two))

    center = _planet_bbox_center(tmp_path, game_id)
    assert center is not None
    assert center[0] > 1500
    assert center[1] > 1500


@pytest.mark.skipif(
    not (REPO_ROOT / ".sampler_data").is_dir(),
    reason="local .sampler_data store only",
)
def test_planet_bbox_center_uses_full_map_not_single_perspective_fog() -> None:
    storage_root = REPO_ROOT / ".sampler_data"
    center = _planet_bbox_center(storage_root, 652072)
    assert center is not None
    assert center == (2005.0, 2002.0)
