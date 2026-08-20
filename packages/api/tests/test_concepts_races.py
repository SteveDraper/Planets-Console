"""Tests for race-specific game concept helpers."""

from dataclasses import replace

from api.concepts.races import (
    HORWASP_RACE_ID,
    evil_empire_free_starbase_fighters_per_host_turn,
    is_horwasp,
)


def test_horwasp_race_id_is_twelve() -> None:
    assert HORWASP_RACE_ID == 12


def test_is_horwasp_matches_horwasp_race_id_only() -> None:
    assert is_horwasp(12) is True
    assert is_horwasp(11) is False
    assert is_horwasp(1) is False


def test_evil_empire_free_starbase_fighters_default_rate_is_five(sample_turn) -> None:
    settings = replace(sample_turn.settings, freestarbasefighters5adjustment=0)
    assert evil_empire_free_starbase_fighters_per_host_turn(settings) == 5


def test_evil_empire_free_starbase_fighters_rate_adds_settings_adjustment(sample_turn) -> None:
    settings = replace(sample_turn.settings, freestarbasefighters5adjustment=3)
    assert evil_empire_free_starbase_fighters_per_host_turn(settings) == 8
