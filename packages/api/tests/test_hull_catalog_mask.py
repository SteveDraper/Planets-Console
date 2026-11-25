"""Tests for inference hull catalog master catalogs and per-player masks."""

import json
from pathlib import Path

import pytest
from api.analytics.export_context import make_analytic_query_context
from api.analytics.military_score_inference.hull_catalog_mask import (
    default_enabled_hull_ids_for_player,
    master_hull_ids_for_race,
    resolve_hull_catalog_mask,
    standard_settings_adjusted_basehulls,
    swaps_for_enabled_settings,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.compute_orchestration import SCORES_PERSISTENCE_POLICY
from api.analytics.scores.hull_mask_overrides import hull_mask_overrides_for
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeScope
from api.serialization.turn import turn_info_from_json
from api.services.stack import build_service_stack
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import scores_export_context

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
    assert resolved.user_enabled_hull_ids == frozenset({99999})
    assert resolved.has_user_override is True


def test_effective_mask_resolves_under_the_current_stored_override(sample_turn):
    overrides = hull_mask_overrides_for(MemoryAssetBackend(initial={}))
    game_id = 628580
    player_id = sample_turn.players[0].id
    default = overrides.effective_mask(sample_turn, game_id, player_id)
    subset = frozenset(sorted(default.master_hull_ids)[:2])

    overrides.change(game_id, player_id, subset)
    masked = overrides.effective_mask(sample_turn, game_id, player_id)
    overrides.change(game_id, player_id, None)
    reset = overrides.effective_mask(sample_turn, game_id, player_id)

    assert default.user_enabled_hull_ids is None
    assert masked.user_enabled_hull_ids == subset
    assert masked.effective_enabled_hull_ids == subset
    assert reset == default


def _fixture_backend_with_turn3() -> tuple[MemoryAssetBackend, int, int, int, int]:
    """Memory backend holding the corpus game info and turn 3 of perspective 1."""
    backend = MemoryAssetBackend(initial={})
    game_id = 628580
    perspective = 1
    turn_number = 3
    backend.put(f"games/{game_id}/info", json.loads(FIXTURE_INFO_PATH.read_text()))
    turn_json = json.loads(FIXTURE_TURN3_PATH.read_text())
    backend.put(f"games/{game_id}/{perspective}/turns/{turn_number}", turn_json)
    player_id = turn_json["scores"][0]["ownerid"]
    return backend, game_id, perspective, turn_number, player_id


def test_a_mask_change_through_one_service_stack_is_seen_through_another():
    backend, game_id, perspective, turn_number, player_id = _fixture_backend_with_turn3()
    writer = build_service_stack(backend).analytics
    reader = build_service_stack(backend).analytics
    initial = reader.get_inference_hull_catalog_mask(game_id, perspective, turn_number, player_id)
    subset = sorted(entry["hullId"] for entry in initial["masterCatalog"])[:2]
    overrides = hull_mask_overrides_for(backend)

    writer.put_inference_hull_catalog_mask(game_id, perspective, turn_number, player_id, subset)

    assert overrides.revision(game_id, player_id) == 1
    seen = reader.get_inference_hull_catalog_mask(game_id, perspective, turn_number, player_id)
    assert seen["userEnabledHullIds"] == subset

    writer.reset_inference_hull_catalog_mask(game_id, perspective, turn_number, player_id)

    assert overrides.revision(game_id, player_id) == 2
    seen = reader.get_inference_hull_catalog_mask(game_id, perspective, turn_number, player_id)
    assert seen["hasUserOverride"] is False


def test_a_mask_change_through_one_stack_moves_the_scores_epoch_another_stack_reads():
    backend, game_id, perspective, turn_number, player_id = _fixture_backend_with_turn3()
    writer = build_service_stack(backend).analytics
    ctx = make_analytic_query_context(
        _load_standard_fixture_turn(),
        TurnAnalyticsOptions(),
        export_services={SCORES_ANALYTIC_ID: scores_export_context(storage=backend)},
        game_id=game_id,
        perspective=perspective,
    )
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective + 1,
        turn=turn_number + 4,
        player_id=player_id,
    )
    before = SCORES_PERSISTENCE_POLICY.invalidation_generation(ctx, scope)
    initial = writer.get_inference_hull_catalog_mask(game_id, perspective, turn_number, player_id)
    subset = sorted(entry["hullId"] for entry in initial["masterCatalog"])[:2]

    writer.put_inference_hull_catalog_mask(game_id, perspective, turn_number, player_id, subset)

    assert SCORES_PERSISTENCE_POLICY.invalidation_generation(ctx, scope) == before + 1


@pytest.mark.skipif(not P5_TURN6_PATH.is_file(), reason="local store only")
def test_hull_catalog_service_put_and_reset_round_trip():
    backend = MemoryAssetBackend(initial={})
    analytics = build_service_stack(backend).analytics

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

    initial = analytics.get_inference_hull_catalog_mask(
        game_id, perspective, turn_number, player_id
    )
    master_ids = {entry["hullId"] for entry in initial["masterCatalog"]}
    assert master_ids

    subset = sorted(master_ids)[:2]
    updated = analytics.put_inference_hull_catalog_mask(
        game_id, perspective, turn_number, player_id, subset
    )
    assert updated["hasUserOverride"] is True
    assert updated["effectiveEnabledHullIds"] == subset

    reset = analytics.reset_inference_hull_catalog_mask(
        game_id, perspective, turn_number, player_id
    )
    assert reset["hasUserOverride"] is False
    assert reset["effectiveEnabledHullIds"] == initial["defaultEnabledHullIds"]
