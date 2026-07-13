"""Tests for hull collision twin asset load/parse (#226)."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.hull_collision_twins_asset import (
    TWIN_ASSET_CATEGORIES,
    HullCollisionTwinTriple,
    load_hull_collision_twins_for_category,
    parse_hull_collision_twins_document,
    twin_pairs_from_triples,
)
from api.concepts.game_category import GameCategory


def test_checked_in_twin_assets_load_for_all_categories() -> None:
    for category in TWIN_ASSET_CATEGORIES:
        asset, path = load_hull_collision_twins_for_category(category)
        assert path.name == f"hull_collision_twins_{category.value}.yaml"
        assert asset.category == category
        assert asset.version == 1
        assert asset.triples
        assert asset.pairs == twin_pairs_from_triples(asset.triples)


def test_epic_twin_asset_includes_birds_valiant_collisions() -> None:
    asset, _ = load_hull_collision_twins_for_category(GameCategory.EPIC)
    assert HullCollisionTwinTriple(30, 31, 2749) in asset.triples
    assert HullCollisionTwinTriple(30, 29, 3281) in asset.triples


def test_parse_rejects_pairs_that_disagree_with_triples() -> None:
    document = {
        "version": 1,
        "category": "epic",
        "source": {
            "catalogGameId": 1,
            "catalogHostTurn": 5,
            "catalogPerspective": 1,
            "earlyPolicyStepId": "early_game_bands",
            "widenHullsPolicyStepId": "widen_hulls",
            "earlyStopMinPlausibility": -300,
            "priorAssetStem": "prior_weights_epic",
        },
        "triples": [
            {"lowHullId": 30, "highHullId": 31, "militaryChange": 2749},
        ],
        "pairs": [
            {"lowHullId": 30, "highHullId": 29},
        ],
    }
    with pytest.raises(ValueError, match="pairs must match"):
        parse_hull_collision_twins_document(document)
