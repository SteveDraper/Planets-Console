"""Unit tests for game category resolution from game settings."""

from dataclasses import replace

from api.concepts.game_category import GameCategory


def test_from_game_settings_campaign_takes_priority(sample_turn):
    settings = replace(
        sample_turn.settings,
        campaignmode=True,
        endturn=30,
        shiplimit=500,
    )
    assert GameCategory.from_game_settings(settings) == GameCategory.CAMPAIGN


def test_from_game_settings_non_campaign_rules(sample_turn):
    base = replace(sample_turn.settings, campaignmode=False)
    assert GameCategory.from_game_settings(replace(base, endturn=30)) == GameCategory.BLITZ
    assert (
        GameCategory.from_game_settings(replace(base, endturn=31, shiplimit=499))
        == GameCategory.STANDARD
    )
    assert (
        GameCategory.from_game_settings(replace(base, endturn=100, shiplimit=500))
        == GameCategory.EPIC
    )


def test_epic_and_standard_require_exactly_eleven_players(sample_turn):
    base = replace(sample_turn.settings, campaignmode=False, endturn=100)
    epic_settings = replace(base, shiplimit=500)
    standard_settings = replace(base, shiplimit=499)

    assert GameCategory.from_game_settings(epic_settings, player_count=11) == GameCategory.EPIC
    assert GameCategory.from_game_settings(epic_settings, player_count=10) == GameCategory.UNKNOWN
    assert GameCategory.from_game_settings(epic_settings, player_count=12) == GameCategory.UNKNOWN
    assert (
        GameCategory.from_game_settings(standard_settings, player_count=11) == GameCategory.STANDARD
    )
    assert (
        GameCategory.from_game_settings(standard_settings, player_count=8) == GameCategory.UNKNOWN
    )


def test_from_game_settings_without_player_count_keeps_shape_category(sample_turn):
    settings = replace(
        sample_turn.settings,
        campaignmode=False,
        endturn=100,
        shiplimit=500,
    )
    assert GameCategory.from_game_settings(settings) == GameCategory.EPIC
