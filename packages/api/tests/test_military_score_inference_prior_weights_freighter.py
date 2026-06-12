"""Tests for freighter prior weight resolution."""

import pytest
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID

from tests.fixtures.military_score_inference_prior_weights import minimal_prior_catalog


def test_freighter_probability_weight_uses_resolved_generic_freighter_weight():
    catalog = minimal_prior_catalog(
        generic_freighter_log_weight=42,
    )
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
        )
        == 42
    )


def test_freighter_probability_weight_prefers_combo_override():
    catalog = minimal_prior_catalog(
        generic_freighter_log_weight=42,
        combo_log_overrides={GENERIC_FREIGHTER_COMBO_ID: 99},
    )
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
        )
        == 99
    )


def test_freighter_probability_weight_rejects_missing_generic_freighter_weight():
    catalog = minimal_prior_catalog(generic_freighter_log_weight=None)

    with pytest.raises(ValueError, match="missing generic freighter marginal weight"):
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
        )
