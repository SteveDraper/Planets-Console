"""Tests for hull catalog analysis helpers and script."""

from __future__ import annotations

from pathlib import Path

import pytest
from api.serialization.turn import turn_info_from_json
from hull_catalog_analysis import (
    compare_hull_set,
    format_hull_id,
    format_hull_set,
    proposed_cross_player_hull_ids,
    standard_settings_adjusted_basehulls,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "packages" / "api" / "tests" / "fixtures" / "inference_corpus"
TURN3_PATH = FIXTURES_ROOT / "628580" / "1" / "turns" / "3.json"
INFO_PATH = FIXTURES_ROOT / "628580" / "info.json"
DATA_ROOT = REPO_ROOT / ".data"


def _load_fixture_turn() -> tuple[object, dict]:
    import json

    settings_defaults = json.loads(INFO_PATH.read_text())["settings"]
    turn = turn_info_from_json(
        json.loads(TURN3_PATH.read_text()),
        settings_defaults=settings_defaults,
    )
    return turn, settings_defaults


def test_format_hull_id_includes_name() -> None:
    names = {90: "Sage Class Frigate", 1090: "Sage Class Repair Ship"}
    assert format_hull_id(90, names) == "90 (Sage Class Frigate)"
    assert format_hull_id(999, names) == "999"


def test_format_hull_set_sorted_with_names() -> None:
    names = {2: "Small Deep Space Freighter", 14: "Large Deep Space Freighter"}
    rendered = format_hull_set(frozenset({14, 2}), names)
    assert rendered == "2 (Small Deep Space Freighter), 14 (Large Deep Space Freighter)"


def test_compare_hull_set_reports_missing_and_extra() -> None:
    comparison = compare_hull_set(
        heuristic_id="race_basehulls",
        candidate=frozenset({1, 2, 3}),
        ground_truth=frozenset({2, 3, 4}),
    )
    assert comparison.covers_ground_truth is False
    assert comparison.missing_from_heuristic == frozenset({4})
    assert comparison.extra_in_heuristic == frozenset({1})
    assert comparison.overage == 1


def test_proposed_cross_player_uses_loaded_racehulls_for_loaded_player() -> None:
    turn, _ = _load_fixture_turn()
    buildable = proposed_cross_player_hull_ids(turn, turn.player.id, settings=turn.settings)
    assert buildable == frozenset(turn.racehulls) & {hull.id for hull in turn.hulls}


@pytest.mark.skipif(not DATA_ROOT.is_dir(), reason="local .data store only")
def test_standard_settings_adjusted_covers_rebel_repair_ship_on_game_628580() -> None:

    from hull_catalog_analysis import analyze_game, load_game_info

    game_info, settings_defaults = load_game_info(DATA_ROOT, 628580)
    analysis = analyze_game(
        DATA_ROOT,
        628580,
        host_turn=6,
        loaded_perspective=1,
        settings_defaults=settings_defaults,
        game_info=game_info,
    )
    rebel = next(player for player in analysis.players if player.player_id == 10)
    proposed = next(
        comparison
        for comparison in rebel.comparisons
        if comparison.heuristic_id == "proposed_cross_player"
    )
    assert proposed.covers_ground_truth
    assert proposed.overage == 0


@pytest.mark.skipif(not DATA_ROOT.is_dir(), reason="local .data store only")
def test_analyze_game_628580_standard_settings_adjusted_full_coverage() -> None:

    from hull_catalog_analysis import analyze_game, load_game_info

    game_info, settings_defaults = load_game_info(DATA_ROOT, 628580)
    analysis = analyze_game(
        DATA_ROOT,
        628580,
        host_turn=6,
        loaded_perspective=1,
        settings_defaults=settings_defaults,
        game_info=game_info,
    )
    summary = next(
        entry
        for entry in analysis.heuristic_summaries
        if entry.heuristic_id == "standard_settings_adjusted"
    )
    assert summary.players_covered == summary.players_with_ground_truth
    assert summary.avg_overage == 0.0


def test_standard_settings_adjusted_swaps_sage_frigate_for_repair_ship() -> None:
    turn, _ = _load_fixture_turn()
    race = next(race for race in turn.races if race.id == 10)
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    adjusted = standard_settings_adjusted_basehulls(
        race_id=10,
        race_basehulls_csv=race.basehulls,
        race_hulls_csv=race.hulls,
        catalog_ids=frozenset(hulls_by_id),
        hulls_by_id=hulls_by_id,
        settings=turn.settings,
    )
    assert 1090 in adjusted
    assert 90 not in adjusted
    assert 87 in adjusted
    assert 1087 not in adjusted


def test_standard_settings_adjusted_skips_repair_ship_when_race_lacks_sage_frigate() -> None:
    turn, _ = _load_fixture_turn()
    race = next(race for race in turn.races if race.id == 9)
    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    adjusted = standard_settings_adjusted_basehulls(
        race_id=9,
        race_basehulls_csv=race.basehulls,
        race_hulls_csv=race.hulls,
        catalog_ids=frozenset(hulls_by_id),
        hulls_by_id=hulls_by_id,
        settings=turn.settings,
    )
    assert 1090 not in adjusted
    assert 90 not in adjusted
