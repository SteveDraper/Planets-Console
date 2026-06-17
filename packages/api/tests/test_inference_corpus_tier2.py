"""Unit tests for Tier 2 multi-perspective ground truth compatibility."""

from tests.inference_corpus.tier2 import compare_ground_truth_to_merged_inventory


def test_compare_ground_truth_passes_when_merged_supports_primary():
    primary = (("combo_1_2_none_none_0_0", 1), ("ship_fighters_added_total", 3))
    merged = (("combo_1_2_none_none_0_0", 1), ("ship_fighters_added_total", 5))
    assert compare_ground_truth_to_merged_inventory(primary, merged) is None


def test_compare_ground_truth_fails_when_primary_exceeds_merged():
    primary = (("ship_fighters_added_total", 5),)
    merged = (("ship_fighters_added_total", 2),)
    error = compare_ground_truth_to_merged_inventory(primary, merged)
    assert error is not None
    assert "exceeds multi-perspective inventory" in error
