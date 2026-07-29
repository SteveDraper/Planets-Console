"""Unit tests for soft origin-distance evidence in layout-prior cost."""

from __future__ import annotations

import math

import pytest
from api.analytics.homeworld_locator.constants import LAYOUT_PRIOR_ALGORITHM_VERSION
from api.analytics.homeworld_locator.layout_prior_cost import (
    ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS,
    origin_distance_evidence_mean,
    origin_distance_observation_neg_log,
)
from api.analytics.homeworld_locator.models import OriginDistanceObservation


def test_layout_prior_algorithm_version_is_six() -> None:
    assert LAYOUT_PRIOR_ALGORITHM_VERSION == 6


def test_observation_neg_log_covers_match_set() -> None:
    observation = OriginDistanceObservation(turn=12, x=100, y=200, matched_planet_ids=(435, 483))
    covering = origin_distance_observation_neg_log(observation, frozenset({435}))
    none = origin_distance_observation_neg_log(observation, frozenset({999}))
    both = origin_distance_observation_neg_log(observation, frozenset({435, 483}))

    assert covering == pytest.approx(-math.log(0.5))
    assert both == pytest.approx(0.0)
    assert none == pytest.approx(-math.log(ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS))
    assert covering < none
    assert both < covering


def test_evidence_blend_math_two_turns() -> None:
    """E = (E + λ e) / (1 + λ) over turn-ordered means; skip empty turns."""
    observations = (
        OriginDistanceObservation(turn=12, x=1, y=1, matched_planet_ids=(10, 20)),
        OriginDistanceObservation(turn=13, x=2, y=2, matched_planet_ids=(10,)),
    )
    selection = frozenset({10})
    lam = 0.8

    e12 = -math.log(0.5)  # |{10}∩{10,20}|/2
    e13 = -math.log(1.0)  # full cover
    expected = 0.0
    expected = (expected + lam * e12) / (1.0 + lam)
    expected = (expected + lam * e13) / (1.0 + lam)

    actual = origin_distance_evidence_mean(observations, selection, evidence_lambda=lam)
    assert actual == pytest.approx(expected)


def test_evidence_skips_empty_turns_and_zero_when_no_observations() -> None:
    assert origin_distance_evidence_mean((), frozenset({1}), evidence_lambda=0.8) == 0.0
    # Only turn 12 has observations; no "empty turn" rows exist in the list.
    observations = (
        OriginDistanceObservation(turn=12, x=0, y=0, matched_planet_ids=(1,)),
        OriginDistanceObservation(turn=14, x=1, y=1, matched_planet_ids=(1,)),
    )
    # Full cover both turns → e=0 each → E stays 0.
    assert origin_distance_evidence_mean(observations, frozenset({1}), evidence_lambda=0.8) == 0.0


def test_ambiguous_match_set_prefers_covering_selection() -> None:
    """Selecting a planet in M is cheaper than selecting neither."""
    observations = (OriginDistanceObservation(turn=12, x=50, y=60, matched_planet_ids=(435, 483)),)
    covering = origin_distance_evidence_mean(observations, frozenset({435}), evidence_lambda=0.8)
    neither = origin_distance_evidence_mean(observations, frozenset({999}), evidence_lambda=0.8)
    assert covering < neither


def test_two_location_observations_cheaper_when_both_covered() -> None:
    """Two co-turn locations: covering both M sets beats covering one."""
    observations = (
        OriginDistanceObservation(turn=12, x=100, y=200, matched_planet_ids=(10,)),
        OriginDistanceObservation(turn=12, x=300, y=400, matched_planet_ids=(20,)),
    )
    both = origin_distance_evidence_mean(observations, frozenset({10, 20}), evidence_lambda=0.8)
    one = origin_distance_evidence_mean(observations, frozenset({10}), evidence_lambda=0.8)
    neither = origin_distance_evidence_mean(observations, frozenset({99}), evidence_lambda=0.8)
    assert both < one < neither
    # Same-turn mean: one miss of two obs → mean((-log 1 + -log ε)/2)
    expected_one = (
        0.0
        + 0.8
        * ((-math.log(1.0) + -math.log(ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS)) / 2.0)
    ) / 1.8
    assert one == pytest.approx(expected_one)
