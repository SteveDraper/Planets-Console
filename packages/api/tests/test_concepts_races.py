"""Tests for race-specific game concept helpers."""

from api.concepts.races import HORWASP_RACE_ID, is_horwasp


def test_horwasp_race_id_is_twelve() -> None:
    assert HORWASP_RACE_ID == 12


def test_is_horwasp_matches_horwasp_race_id_only() -> None:
    assert is_horwasp(12) is True
    assert is_horwasp(11) is False
    assert is_horwasp(1) is False
