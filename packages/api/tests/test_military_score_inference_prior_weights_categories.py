"""Unit tests for inference hull category resolution."""

from dataclasses import replace

from api.analytics.military_score_inference.hull_category import resolve_inference_hull_category

from tests.fixtures.military_score_inference_prior_weights import (
    battleship_hull,
    beam_ship_hull,
    torpedo_hull,
)


def test_resolve_inference_hull_category_priority():
    freighter = replace(beam_ship_hull(), id=15, beams=0, launchers=0, fighterbays=0)
    assert resolve_inference_hull_category(freighter) == "true_freighter"
    assert resolve_inference_hull_category(beam_ship_hull(), beam_count=0, launcher_count=0) == (
        "weaponless_hull"
    )
    assert resolve_inference_hull_category(torpedo_hull(), beam_count=0, launcher_count=0) == (
        "weaponless_hull"
    )
    assert resolve_inference_hull_category(battleship_hull(), beam_count=0, launcher_count=0) == (
        "weaponless_hull"
    )
    carrier = replace(beam_ship_hull(), fighterbays=4, beams=0)
    assert resolve_inference_hull_category(carrier) == "carrier"
    assert resolve_inference_hull_category(torpedo_hull(), beam_count=1, launcher_count=2) == (
        "torpedo_ship"
    )
    assert resolve_inference_hull_category(battleship_hull(), beam_count=4, launcher_count=4) == (
        "battleship"
    )
    assert resolve_inference_hull_category(beam_ship_hull(), beam_count=2, launcher_count=0) == (
        "beam_ship"
    )
