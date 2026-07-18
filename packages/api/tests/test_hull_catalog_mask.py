"""Tests for inference hull catalog master catalogs and per-player masks."""

import json
from pathlib import Path

import pytest
from api.analytics.military_score_inference.hull_catalog_mask import (
    default_enabled_hull_ids_for_player,
    master_hull_ids_for_race,
    resolve_hull_catalog_mask,
    standard_settings_adjusted_basehulls,
    swaps_for_enabled_settings,
)
from api.serialization.turn import turn_info_from_json
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

REPO_ROOT = Path(__file__).resolve().parents[3]
P5_TURN6_PATH = REPO_ROOT / ".data" / "games" / "628580" / "5" / "turns" / "6.json"
_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "inference_corpus" / "628580"
FIXTURE_TURN3_PATH = _FIXTURE_ROOT / "1" / "turns" / "3.json"
FIXTURE_INFO_PATH = _FIXTURE_ROOT / "info.json"


def _load_standard_fixture_turn():
    settings_defaults = json.loads(FIXTURE_INFO_PATH.read_text())["settings"]
    return turn_info_from_json(
        json.loads(FIXTURE_TURN3_PATH.read_text()),
        settings_defaults=settings_defaults,
    )


def test_swaps_for_enabled_settings_are_fixed_pairs_not_parentid_walk():
    turn = _load_standard_fixture_turn()
    race = next(entry for entry in turn.races if entry.id == 10)
    from api.analytics.military_score_inference.inference_turn_lookup import parse_component_id_csv

    base_hull_ids = parse_component_id_csv(race.basehulls)
    swaps = swaps_for_enabled_settings(
        settings=turn.settings,
        base_hull_ids=base_hull_ids,
    )
    assert swaps == [(90, 1090)]


def test_standard_settings_rebel_keeps_falcon_and_swaps_only_sage():
    turn = _load_standard_fixture_turn()
    race = next(entry for entry in turn.races if entry.id == 10)
    catalog_ids = frozenset(hull.id for hull in turn.hulls)
    adjusted = standard_settings_adjusted_basehulls(
        race_id=10,
        race_basehulls_csv=race.basehulls,
        race_hulls_csv=race.hulls,
        catalog_ids=catalog_ids,
        settings=turn.settings,
    )
    assert 87 in adjusted
    assert 1087 not in adjusted
    assert 1090 in adjusted
    assert 90 not in adjusted
    assert 88 in adjusted
    assert 1088 not in adjusted


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


def test_user_override_intersects_master(sample_turn):
    player_id = sample_turn.players[0].id
    resolved = resolve_hull_catalog_mask(
        sample_turn,
        player_id,
        user_enabled_hull_ids=frozenset({99999}),
    )
    assert 99999 not in resolved.effective_enabled_hull_ids
    assert resolved.has_user_override is True


@pytest.mark.skipif(not P5_TURN6_PATH.is_file(), reason="local store only")
def test_hull_catalog_service_put_and_reset_round_trip():
    backend = MemoryAssetBackend(initial={})
    _, turns, _, _, analytics = build_service_stack(backend)
    service = analytics._hull_catalog_masks

    game_id = 628580
    perspective = 5
    turn_number = 6
    player_id = 5
    with open(REPO_ROOT / ".data" / "games" / "628580" / "info.json") as handle:
        backend.put(f"games/{game_id}/info", json.load(handle))
    with open(P5_TURN6_PATH) as handle:
        backend.put(
            f"games/{game_id}/{perspective}/turns/{turn_number}",
            json.load(handle),
        )

    initial = service.hull_catalog_mask_payload(game_id, perspective, turn_number, player_id)
    master_ids = {entry["hullId"] for entry in initial["masterCatalog"]}
    assert master_ids

    subset = sorted(master_ids)[:2]
    updated = service.put_user_mask(game_id, perspective, turn_number, player_id, subset)
    assert updated["hasUserOverride"] is True
    assert updated["effectiveEnabledHullIds"] == subset

    reset = service.reset_user_mask(game_id, perspective, turn_number, player_id)
    assert reset["hasUserOverride"] is False
    assert reset["effectiveEnabledHullIds"] == initial["defaultEnabledHullIds"]
