"""Unit tests for Laplace smoothing and wildcard count helpers."""

from api.analytics.military_score_inference.prior_weights_laplace import (
    counts_to_log_weights,
    expand_wildcard_counts,
    implicit_uniform_component_counts,
)


def test_counts_to_log_weights_prefers_likely_cells():
    likely = counts_to_log_weights({1: 900, 2: 100})
    unlikely = counts_to_log_weights({1: 100, 2: 900})
    assert likely[1] > likely[2]
    assert unlikely[1] < unlikely[2]


def test_expand_wildcard_counts_fills_universe():
    expanded = expand_wildcard_counts(
        {"*": 10, 24: 100},
        universe=frozenset({24, 15}),
    )
    assert expanded == {24: 100, 15: 10}


def test_implicit_uniform_component_counts_are_equal_per_id():
    counts = implicit_uniform_component_counts(frozenset({2, 3, 5}))
    assert counts == {2: 1.0, 3: 1.0, 5: 1.0}
