"""Tests for homeworld extraction helpers and script."""

from __future__ import annotations

import csv
import json
import shutil
from io import StringIO
from pathlib import Path

import pytest
from api.concepts.game_category import GameCategory
from api.serialization.turn import turn_info_from_json
from homeworld_extraction import (
    BASELINE_TURN,
    GameHomeworlds,
    HomeworldLocation,
    extract_homeworlds_by_category,
    extract_homeworlds_for_game,
    flatten_homeworld_rows,
    homeworld_planet_for_turn,
    matches_homeworld_baseline_profile,
    preferred_homeworld_temp_w,
    write_homeworld_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "packages" / "api" / "tests" / "fixtures" / "inference_corpus"
DATA_ROOT = REPO_ROOT / ".data"


@pytest.fixture
def fixture_storage_root(tmp_path: Path) -> Path:
    destination = tmp_path / "games" / "628580"
    shutil.copytree(FIXTURES_ROOT / "628580", destination)
    return tmp_path


def _load_fixture_turn(*, perspective: int = 1):
    settings_defaults = json.loads((FIXTURES_ROOT / "628580" / "info.json").read_text())["settings"]
    turn_path = FIXTURES_ROOT / "628580" / str(perspective) / "turns" / f"{BASELINE_TURN}.json"
    turn = turn_info_from_json(
        json.loads(turn_path.read_text()),
        settings_defaults=settings_defaults,
    )
    return turn, settings_defaults


def test_preferred_homeworld_temp_w_for_crystal_desert_advantage() -> None:
    assert preferred_homeworld_temp_w(race_id=7, active_advantages=frozenset({21})) == 100
    assert preferred_homeworld_temp_w(race_id=7, active_advantages=frozenset()) == 50
    assert preferred_homeworld_temp_w(race_id=1, active_advantages=frozenset({21})) == 50


def test_matches_homeworld_baseline_profile_on_fixture_turn_1() -> None:
    turn, _ = _load_fixture_turn(perspective=1)
    owned = next(planet for planet in turn.planets if planet.ownerid == turn.player.id)
    assert matches_homeworld_baseline_profile(owned, turn=turn, settings=turn.settings)


def test_homeworld_planet_for_turn_returns_owned_planet() -> None:
    turn, _ = _load_fixture_turn(perspective=1)
    planet = homeworld_planet_for_turn(turn)
    assert planet is not None
    assert planet.name == "Lynch"
    assert planet.x == 1813
    assert planet.y == 2810


def test_extract_homeworlds_for_fixture_game_is_epic(fixture_storage_root: Path) -> None:
    extracted = extract_homeworlds_for_game(fixture_storage_root, 628580)
    assert extracted is not None
    assert extracted.game_type == GameCategory.EPIC
    assert len(extracted.homeworlds) == 1
    assert extracted.homeworlds[0].player == "dougp314"
    assert extracted.homeworlds[0].x == 1813
    assert extracted.homeworlds[0].y == 2810


def test_extract_homeworlds_by_category_skips_campaign_games(fixture_storage_root: Path) -> None:
    grouped = extract_homeworlds_by_category(fixture_storage_root)
    assert grouped[GameCategory.EPIC]
    assert grouped[GameCategory.STANDARD] == []
    assert all(item.game_id == 628580 for item in grouped[GameCategory.EPIC])


def test_write_homeworld_csv_columns() -> None:
    extracted = GameHomeworlds(
        game_id=628580,
        game_type=GameCategory.EPIC,
        homeworlds=(HomeworldLocation(player="dougp314", x=1813, y=2810),),
    )
    buffer = StringIO()
    write_homeworld_csv(flatten_homeworld_rows({GameCategory.EPIC: [extracted]}), buffer)
    rows = list(csv.DictReader(StringIO(buffer.getvalue())))
    assert rows == [
        {
            "game_type": "epic",
            "game_id": "628580",
            "player": "dougp314",
            "x": "1813",
            "y": "2810",
        }
    ]


@pytest.mark.skipif(not DATA_ROOT.is_dir(), reason="local .data store only")
def test_extract_homeworlds_for_local_epic_game_has_multiple_players() -> None:
    extracted = extract_homeworlds_for_game(DATA_ROOT, 628580)
    assert extracted is not None
    assert extracted.game_type == GameCategory.EPIC
    assert len(extracted.homeworlds) >= 10
