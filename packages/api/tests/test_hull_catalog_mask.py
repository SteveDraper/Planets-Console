"""Tests for inference hull catalog master catalogs and default hull eligibility."""

from api.analytics.military_score_inference.hull_catalog_mask import (
    default_enabled_hull_ids_for_player,
    master_hull_ids_for_race,
)


def test_master_hull_ids_intersects_turn_catalog(sample_turn):
    race_with_hulls = next(
        race for race in sample_turn.races if master_hull_ids_for_race(sample_turn, race.id)
    )
    master = master_hull_ids_for_race(sample_turn, race_with_hulls.id)
    catalog = {hull.id for hull in sample_turn.hulls}
    assert master <= catalog


def test_standard_default_uses_settings_adjusted_basehulls_not_loaded_racehulls(sample_turn):
    other_player_id = next(
        player.id for player in sample_turn.players if player.id != sample_turn.player.id
    )
    enabled = default_enabled_hull_ids_for_player(sample_turn, other_player_id)
    assert enabled
    assert enabled != frozenset(sample_turn.racehulls)


def test_loaded_perspective_player_uses_turn_racehulls(sample_turn):
    enabled = default_enabled_hull_ids_for_player(sample_turn, sample_turn.player.id)
    catalog = {hull.id for hull in sample_turn.hulls}
    assert enabled == frozenset(sample_turn.racehulls) & catalog
