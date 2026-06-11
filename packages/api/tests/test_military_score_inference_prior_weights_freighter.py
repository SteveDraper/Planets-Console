"""Tests for freighter pseudo-hull prior weight resolution."""

from api.analytics.military_score_inference.prior_weights_catalog import (
    GENERIC_FREIGHTER_PRIOR_HULL_ID,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID

from tests.fixtures.military_score_inference_prior_weights import minimal_prior_catalog


def test_freighter_probability_weight_uses_pseudo_hull_marginal():
    catalog = minimal_prior_catalog(
        hull_log_weights={GENERIC_FREIGHTER_PRIOR_HULL_ID: 42},
    )
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 42
    )


def test_freighter_probability_weight_prefers_combo_then_hull_override():
    catalog = minimal_prior_catalog(
        hull_log_weights={GENERIC_FREIGHTER_PRIOR_HULL_ID: 42},
        hull_log_overrides={GENERIC_FREIGHTER_PRIOR_HULL_ID: 55},
        combo_log_overrides={GENERIC_FREIGHTER_COMBO_ID: 99},
    )
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 99
    )
    without_combo = minimal_prior_catalog(
        hull_log_weights={GENERIC_FREIGHTER_PRIOR_HULL_ID: 42},
        hull_log_overrides={GENERIC_FREIGHTER_PRIOR_HULL_ID: 55},
    )
    assert (
        without_combo.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 55
    )


def test_freighter_probability_weight_falls_back_to_default():
    catalog = minimal_prior_catalog()
    assert (
        catalog.freighter_probability_weight(
            combo_id=GENERIC_FREIGHTER_COMBO_ID,
            default_weight=80,
        )
        == 80
    )
