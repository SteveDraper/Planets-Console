"""Tests for inference build prior asset parsing and loading."""

from pathlib import Path

import pytest
from api.analytics.military_score_inference.aggregate_action_registry import AGGREGATE_ACTION_SPECS
from api.analytics.military_score_inference.prior_weights_asset import (
    load_prior_weights_for_category,
    parse_prior_weights_document,
)
from api.analytics.military_score_inference.prior_weights_laplace import WILDCARD_COUNT_KEY
from api.concepts.game_category import GAME_CATEGORY_RULES_VERSION, GameCategory

from tests.fixtures.hand_seeded_prior_weights import (
    HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    HAND_SEEDED_STANDARD_PRIOR_PATH,
)


def _complete_aggregates_band() -> dict[str, object]:
    band: dict[str, object] = {}
    for action_id in AGGREGATE_ACTION_SPECS:
        band[action_id] = {"histogram": {0: 5, 1: 1}}
    return band


def _minimal_prior_weights_document(**overrides: object) -> dict[str, object]:
    complete_band = _complete_aggregates_band()
    document: dict[str, object] = {
        "version": 4,
        "category": "standard",
        "gameCategoryRulesVersion": 2,
        "hulls": {
            "before_ship_limit": {"global": {}},
            "after_ship_limit": {"global": {}},
        },
        "components": {
            "before_ship_limit": {},
            "after_ship_limit": {},
        },
        "aggregates": {
            "before_ship_limit": dict(complete_band),
            "after_ship_limit": dict(complete_band),
        },
    }
    document.update(overrides)
    return document


def test_hand_seeded_standard_prior_fixture_loads():
    asset, path, fell_back = load_prior_weights_for_category(
        GameCategory.STANDARD,
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    )
    assert not fell_back
    assert path == HAND_SEEDED_STANDARD_PRIOR_PATH
    assert asset.category == GameCategory.STANDARD
    assert asset.version == 4
    assert asset.hulls["before_ship_limit"]["global"]["beam_ship"][WILDCARD_COUNT_KEY] == 50


def test_production_standard_prior_asset_loads():
    asset, path, fell_back = load_prior_weights_for_category(GameCategory.STANDARD)
    assert not fell_back
    assert path.name == "prior_weights_standard.yaml"
    assert asset.category == GameCategory.STANDARD
    assert asset.version == 4


def test_missing_category_falls_back_to_standard(tmp_path: Path):
    tmp_path.joinpath("prior_weights_standard.yaml").write_text(
        HAND_SEEDED_STANDARD_PRIOR_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    asset, path, fell_back = load_prior_weights_for_category(
        GameCategory.BLITZ,
        base_dir=tmp_path,
    )
    assert fell_back
    assert path.name == "prior_weights_standard.yaml"
    assert asset.category == GameCategory.STANDARD


def test_game_category_rules_version_must_match_expected_rules():
    with pytest.raises(ValueError, match="does not match expected game category rules version"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                gameCategoryRulesVersion=GAME_CATEGORY_RULES_VERSION + 1,
            )
        )


def test_histogram_rejects_wildcard_key():
    before_ship_limit = _complete_aggregates_band()
    before_ship_limit["planet_defense_posts_added_total"] = {"histogram": {"*": 10, 5: 1}}
    with pytest.raises(ValueError, match="must be integers"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": before_ship_limit,
                    "after_ship_limit": _complete_aggregates_band(),
                }
            )
        )


def test_histogram_rejects_negative_magnitude_key():
    before_ship_limit = _complete_aggregates_band()
    before_ship_limit["planet_defense_posts_added_total"] = {"histogram": {-1: 10, 5: 1}}
    with pytest.raises(ValueError, match="keys must be non-negative integers"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": before_ship_limit,
                    "after_ship_limit": _complete_aggregates_band(),
                }
            )
        )


def test_aggregates_reject_unknown_histogram_action_id():
    with pytest.raises(ValueError, match="not a known aggregate action"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": {
                        **_complete_aggregates_band(),
                        "planet_defense_posts_typo": {"histogram": {5: 1}},
                    },
                    "after_ship_limit": _complete_aggregates_band(),
                }
            )
        )


def test_aggregates_reject_malformed_template_action_id():
    with pytest.raises(ValueError, match="not a known aggregate action"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": {
                        **_complete_aggregates_band(),
                        "ship_torps_loaded_typo": {"histogram": {0: 5, 1: 1}},
                    },
                    "after_ship_limit": _complete_aggregates_band(),
                }
            )
        )


def test_aggregates_reject_counts_shape():
    """The counts shape no longer exists; guard against accidental reintroduction."""
    before_ship_limit = _complete_aggregates_band()
    before_ship_limit["fighters_starbase_to_ship"] = {"counts": {"default": 65}}
    with pytest.raises(ValueError, match="must include a histogram"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": before_ship_limit,
                    "after_ship_limit": _complete_aggregates_band(),
                }
            )
        )


def test_histogram_accepts_and_routes_zero_occurrence_key():
    asset = parse_prior_weights_document(
        _minimal_prior_weights_document(
            aggregates={
                "before_ship_limit": {
                    **_complete_aggregates_band(),
                    "planet_defense_posts_added_total": {"histogram": {0: 200, 5: 120}},
                },
                "after_ship_limit": _complete_aggregates_band(),
            }
        )
    )
    histogram = asset.aggregates["before_ship_limit"]["planet_defense_posts_added_total"].histogram
    assert histogram[0] == 200
    assert histogram[5] == 120


def test_histogram_without_zero_key_still_parses():
    """Occurrence mass is opt-in: a histogram missing its 0 key parses (no none seed)."""
    before_ship_limit = _complete_aggregates_band()
    before_ship_limit["planet_defense_posts_added_total"] = {"histogram": {5: 120}}
    asset = parse_prior_weights_document(
        _minimal_prior_weights_document(
            aggregates={
                "before_ship_limit": before_ship_limit,
                "after_ship_limit": _complete_aggregates_band(),
            }
        )
    )
    histogram = asset.aggregates["before_ship_limit"]["planet_defense_posts_added_total"].histogram
    assert 0 not in histogram


def test_parse_rejects_incomplete_aggregate_priors():
    incomplete_band = _complete_aggregates_band()
    del incomplete_band["planet_defense_posts_added_total"]
    with pytest.raises(ValueError, match="incomplete prior"):
        parse_prior_weights_document(
            _minimal_prior_weights_document(
                aggregates={
                    "before_ship_limit": incomplete_band,
                    "after_ship_limit": _complete_aggregates_band(),
                }
            )
        )


def test_component_tables_reject_unknown_hull_category():
    with pytest.raises(ValueError, match="not a valid inference hull category"):
        parse_prior_weights_document(
            {
                "version": 4,
                "category": "standard",
                "gameCategoryRulesVersion": 2,
                "hulls": {
                    "before_ship_limit": {"global": {}},
                    "after_ship_limit": {"global": {}},
                },
                "components": {
                    "before_ship_limit": {"beam_ships": {"engines": {1: 1}}},
                    "after_ship_limit": {},
                },
                "aggregates": {
                    "before_ship_limit": _complete_aggregates_band(),
                    "after_ship_limit": _complete_aggregates_band(),
                },
            }
        )


def test_slotfill_rejects_wildcard_key():
    with pytest.raises(ValueError, match="does not allow '\\*'"):
        parse_prior_weights_document(
            {
                "version": 4,
                "category": "standard",
                "gameCategoryRulesVersion": 2,
                "hulls": {
                    "before_ship_limit": {"global": {}},
                    "after_ship_limit": {"global": {}},
                },
                "components": {
                    "before_ship_limit": {"beam_ship": {"slotFill": {"*": 10, "full": 1}}},
                    "after_ship_limit": {},
                },
                "aggregates": {
                    "before_ship_limit": _complete_aggregates_band(),
                    "after_ship_limit": _complete_aggregates_band(),
                },
            }
        )
