"""Tests for loadall ZIP parsing."""

import io
import json
import zipfile

import pytest
from api.errors import UpstreamPlanetsError, ValidationError
from api.services.load_all_archive import parse_load_all_zip


def _zip_with(entries: dict[str, dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, rst in entries.items():
            archive.writestr(name, json.dumps(rst))
    return buf.getvalue()


def test_parse_load_all_zip_extracts_turn_files() -> None:
    payload = _zip_with(
        {
            "player2-turn1.trn": {"settings": {"turn": 1}, "game": {"id": 1, "turn": 1}},
            "player1-turn2.trn": {"settings": {"turn": 2}, "game": {"id": 1, "turn": 2}},
        }
    )
    parsed = parse_load_all_zip(payload)
    assert len(parsed) == 2
    by_key = {(entry.player_slot, entry.turn_number): entry.rst for entry in parsed}
    assert by_key[(2, 1)]["settings"]["turn"] == 1
    assert by_key[(1, 2)]["settings"]["turn"] == 2


def test_parse_load_all_zip_rejects_empty_archive() -> None:
    payload = _zip_with({"readme.txt": {}})
    with pytest.raises(UpstreamPlanetsError, match="no turn files"):
        parse_load_all_zip(payload)


def test_parse_load_all_zip_accepts_spectator_slot_zero() -> None:
    payload = _zip_with(
        {
            "player0-turn1.trn": {"settings": {"turn": 1}, "game": {"id": 1, "turn": 1}},
            "player1-turn1.trn": {"settings": {"turn": 1}, "game": {"id": 1, "turn": 1}},
        }
    )
    parsed = parse_load_all_zip(payload)
    assert {(entry.player_slot, entry.turn_number) for entry in parsed} == {(0, 1), (1, 1)}


def test_parse_load_all_zip_rejects_invalid_json() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("player1-turn1.trn", b"not-json")
    with pytest.raises(ValidationError, match="valid JSON"):
        parse_load_all_zip(buf.getvalue())
