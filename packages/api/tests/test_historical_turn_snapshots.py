"""Regression tests for deserializing historical turn snapshots from loadall archives."""

import json
import zipfile
from pathlib import Path

import pytest
from api.serialization.turn import turn_info_from_json

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"
ZIP_PATH = Path("/tmp/game628580.zip")


@pytest.fixture(scope="module")
def game_settings_defaults() -> dict:
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        return json.load(handle)["settings"]


@pytest.mark.skipif(not ZIP_PATH.is_file(), reason="loadall sample zip not present")
@pytest.mark.parametrize("turn_number", [1, 50, 83, 84, 110])
def test_loadall_archive_turns_deserialize(game_settings_defaults: dict, turn_number: int) -> None:
    with zipfile.ZipFile(ZIP_PATH) as archive:
        raw = json.loads(archive.read(f"player1-turn{turn_number}.trn"))
    turn_info_from_json(raw, settings_defaults=game_settings_defaults)
