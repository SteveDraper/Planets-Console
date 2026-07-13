"""Tests for hull collision twin asset load/parse (#226)."""

from __future__ import annotations

import yaml
from api.analytics.military_score_inference.hull_collision_twins_asset import (
    TWIN_ASSET_CATEGORIES,
    HullCollisionTwinTriple,
    default_twin_asset_path,
    load_hull_collision_twins_for_category,
    parse_hull_collision_twins_document,
    twin_pairs_from_triples,
    twins_asset_to_document,
)
from api.concepts.game_category import GameCategory

_SOURCE = {
    "catalogGameId": 1,
    "catalogHostTurn": 5,
    "catalogPerspective": 1,
    "earlyPolicyStepId": "early_game_bands",
    "widenHullsPolicyStepId": "widen_hulls",
    "earlyStopMinPlausibility": -300,
    "priorAssetStem": "prior_weights_epic",
}


def test_checked_in_twin_assets_load_for_all_categories() -> None:
    for category in TWIN_ASSET_CATEGORIES:
        asset, path = load_hull_collision_twins_for_category(category)
        assert path.name == f"hull_collision_twins_{category.value}.yaml"
        assert asset.category == category
        assert asset.version == 1
        assert asset.triples
        assert asset.pairs == twin_pairs_from_triples(asset.triples)


def test_checked_in_twin_assets_do_not_persist_pairs() -> None:
    for category in TWIN_ASSET_CATEGORIES:
        path = default_twin_asset_path(category)
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict)
        assert "pairs" not in document
        assert "triples" in document


def test_epic_twin_asset_includes_birds_valiant_collisions() -> None:
    asset, _ = load_hull_collision_twins_for_category(GameCategory.EPIC)
    assert HullCollisionTwinTriple(30, 31, 2749) in asset.triples
    assert HullCollisionTwinTriple(30, 29, 3281) in asset.triples


def test_parse_derives_pairs_from_triples() -> None:
    document = {
        "version": 1,
        "category": "epic",
        "source": _SOURCE,
        "triples": [
            {"lowHullId": 30, "highHullId": 31, "militaryChange": 2749},
            {"lowHullId": 30, "highHullId": 29, "militaryChange": 3281},
            {"lowHullId": 30, "highHullId": 31, "militaryChange": 3000},
        ],
    }
    asset = parse_hull_collision_twins_document(document)
    assert asset.pairs == twin_pairs_from_triples(asset.triples)
    assert {(p.low_hull_id, p.high_hull_id) for p in asset.pairs} == {(30, 29), (30, 31)}


def test_parse_ignores_legacy_pairs_key() -> None:
    document = {
        "version": 1,
        "category": "epic",
        "source": _SOURCE,
        "triples": [
            {"lowHullId": 30, "highHullId": 31, "militaryChange": 2749},
        ],
        "pairs": [
            {"lowHullId": 30, "highHullId": 29},
        ],
    }
    asset = parse_hull_collision_twins_document(document)
    assert asset.pairs == twin_pairs_from_triples(asset.triples)
    assert len(asset.pairs) == 1
    assert asset.pairs[0].low_hull_id == 30
    assert asset.pairs[0].high_hull_id == 31


def test_twins_asset_to_document_omits_pairs() -> None:
    document = {
        "version": 1,
        "category": "epic",
        "source": _SOURCE,
        "triples": [
            {"lowHullId": 30, "highHullId": 31, "militaryChange": 2749},
        ],
    }
    asset = parse_hull_collision_twins_document(document)
    serialized = twins_asset_to_document(asset)
    assert "pairs" not in serialized
    assert serialized["triples"] == document["triples"]
