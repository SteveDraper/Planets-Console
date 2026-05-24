"""Tests for sector display name extraction."""

import json
from pathlib import Path

from api.serialization.game import game_info_from_json
from api.transport.sector_display import (
    sector_display_name_from_game_info,
    sector_display_name_from_stored_payload,
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def test_sector_display_name_from_stored_payload_prefers_game_name():
    raw = {"game": {"name": "Alpha"}, "settings": {"name": "Beta"}}
    assert sector_display_name_from_stored_payload(raw) == "Alpha"


def test_sector_display_name_from_stored_payload_falls_back_to_settings():
    payload = {"settings": {"name": "Only Here"}}
    assert sector_display_name_from_stored_payload(payload) == "Only Here"


def test_sector_display_name_from_game_info_matches_payload_helper():
    with open(ASSETS_DIR / "game_info_sample.json") as f:
        payload = json.load(f)
    info = game_info_from_json(payload)
    assert sector_display_name_from_game_info(info) == "Serada 9 Sector"
    assert sector_display_name_from_stored_payload(payload) == "Serada 9 Sector"
