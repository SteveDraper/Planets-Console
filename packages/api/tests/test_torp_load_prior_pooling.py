"""Tests for pooled any-torp-load prior resolution."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ANY_PRIOR_KEY,
)
from api.analytics.military_score_inference.prior_weights_asset import HistogramAggregate
from api.analytics.military_score_inference.prior_weights_resolve import (
    _resolve_any_torp_load_bucket_weights,
    resolve_prior_weights_catalog,
)
from api.analytics.military_score_inference.tier_policy import aggregate_bin_bounds_for_key
from api.analytics.military_score_inference.torp_load_prior_pooling import (
    synthesize_any_torp_load_histogram,
)

from tests.fixtures.hand_seeded_prior_weights import HAND_SEEDED_PRIOR_WEIGHTS_DIR
from tests.test_military_score_inference_prior_weights_catalog_resolution import _observation


def test_synthesize_any_torp_histogram_uses_total_sample_mass():
    band_tables = {
        "ship_torps_loaded_1": HistogramAggregate(histogram={0: 8, 5: 2}),
        "ship_torps_loaded_2": HistogramAggregate(histogram={0: 9, 10: 1}),
    }
    synthesized = synthesize_any_torp_load_histogram(band_tables, frozenset({1, 2}))
    assert sum(synthesized.histogram.values()) == 10
    assert synthesized.histogram[0] == 7
    assert synthesized.histogram[5] == 2
    assert synthesized.histogram[10] == 1


def test_all_torp_types_share_pooled_bucket_weights(sample_turn):
    catalog = resolve_prior_weights_catalog(
        _observation(),
        replace(sample_turn.settings, endturn=100, shiplimit=200),
        buildable_hull_ids=frozenset({24}),
        eligible_engine_ids=frozenset({1}),
        eligible_beam_ids=frozenset({1}),
        eligible_torp_ids=frozenset({1, 6, 9}),
        base_dir=HAND_SEEDED_PRIOR_WEIGHTS_DIR,
    )
    torp_bins = aggregate_bin_bounds_for_key("ship_torps_per_type")
    mk1 = catalog.probability_buckets_for_action("ship_torps_loaded_1", torp_bins)
    mk4 = catalog.probability_buckets_for_action("ship_torps_loaded_6", torp_bins)
    mk7 = catalog.probability_buckets_for_action("ship_torps_loaded_9", torp_bins)
    assert tuple(bucket.marginal_weight for bucket in mk1) == tuple(
        bucket.marginal_weight for bucket in mk4
    )
    assert tuple(bucket.marginal_weight for bucket in mk1) == tuple(
        bucket.marginal_weight for bucket in mk7
    )


def test_mined_any_torp_histogram_overrides_synthesized_weights():
    band_tables = {
        "ship_torps_loaded_1": HistogramAggregate(histogram={0: 8, 5: 2}),
        SHIP_TORPS_LOADED_ANY_PRIOR_KEY: HistogramAggregate(histogram={0: 90, 10: 10}),
    }
    weights = _resolve_any_torp_load_bucket_weights(
        band_tables,
        eligible_torp_ids=frozenset({1}),
        scale=100,
    )
    synthesized_only = _resolve_any_torp_load_bucket_weights(
        {"ship_torps_loaded_1": HistogramAggregate(histogram={0: 8, 5: 2})},
        eligible_torp_ids=frozenset({1}),
        scale=100,
    )
    assert weights != synthesized_only
