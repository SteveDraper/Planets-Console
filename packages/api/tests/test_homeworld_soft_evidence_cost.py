"""Unit tests for soft origin-distance evidence in layout-prior cost."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.constants import (
    HOMEWORLD_BASELINE_ALGORITHM_VERSION,
    HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
    LAYOUT_PRIOR_ALGORITHM_VERSION,
)
from api.analytics.homeworld_locator.layout_prior_cost import (
    ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS,
    origin_distance_evidence_mean,
    origin_distance_observation_neg_log,
    origin_distance_update_weight,
)
from api.analytics.homeworld_locator.models import OriginDistanceObservation
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.serialization.turn import turn_info_from_json
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    return MemoryAssetBackend(initial={})


@pytest.fixture
def persistence(memory_backend):
    return HomeworldLocatorPersistenceService(memory_backend)


@pytest.fixture
def sample_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


@pytest.fixture
def template_planet(sample_turn):
    return sample_turn.planets[0]


def test_layout_prior_algorithm_version_is_ten() -> None:
    assert LAYOUT_PRIOR_ALGORITHM_VERSION == 10


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


def test_update_weight_is_lambda_to_the_turn() -> None:
    assert origin_distance_update_weight(0, 0.95) == pytest.approx(1.0)
    assert origin_distance_update_weight(1, 0.95) == pytest.approx(0.95)
    assert origin_distance_update_weight(20, 0.95) == pytest.approx(0.95**20)
    assert origin_distance_update_weight(55, 0.95) == pytest.approx(0.95**55)
    # Late turns are weak relative to early mid-game.
    assert origin_distance_update_weight(55, 0.95) < origin_distance_update_weight(12, 0.95)


def test_evidence_blend_uses_absolute_turn_weights() -> None:
    """E = (E + w(t) e) / (1 + w(t)) with w(t)=λ^t; skip empty turns."""
    observations = (
        OriginDistanceObservation(turn=12, x=1, y=1, matched_planet_ids=(10, 20)),
        OriginDistanceObservation(turn=13, x=2, y=2, matched_planet_ids=(10,)),
    )
    selection = frozenset({10})
    lam = 0.95

    e12 = -math.log(0.5)  # |{10}∩{10,20}|/2
    e13 = -math.log(1.0)  # full cover
    w12 = lam**12
    w13 = lam**13
    expected = 0.0
    expected = (expected + w12 * e12) / (1.0 + w12)
    expected = (expected + w13 * e13) / (1.0 + w13)

    actual = origin_distance_evidence_mean(observations, selection, evidence_lambda=lam)
    assert actual == pytest.approx(expected)


def test_empty_turns_do_not_change_evidence_when_observation_list_unchanged() -> None:
    """Invariant: no new observations ⇒ same E (barren calendar gaps are no-ops)."""
    early = (
        OriginDistanceObservation(turn=12, x=0, y=0, matched_planet_ids=(1,)),
        OriginDistanceObservation(turn=14, x=1, y=1, matched_planet_ids=(2,)),
    )
    # Same nonempty turns; calendar "gaps" are absent rows, not decaying updates.
    selection = frozenset({1})
    first = origin_distance_evidence_mean(early, selection, evidence_lambda=0.95)
    second = origin_distance_evidence_mean(early, selection, evidence_lambda=0.95)
    assert first == second
    assert origin_distance_evidence_mean((), frozenset({1}), evidence_lambda=0.95) == 0.0
    # Full cover both turns → e=0 each → E stays 0.
    covered = (
        OriginDistanceObservation(turn=12, x=0, y=0, matched_planet_ids=(1,)),
        OriginDistanceObservation(turn=14, x=1, y=1, matched_planet_ids=(1,)),
    )
    assert origin_distance_evidence_mean(covered, frozenset({1}), evidence_lambda=0.95) == 0.0


def test_late_update_weaker_than_early_for_same_turn_mean() -> None:
    """Identical e_t moves E less at T55 than at T12 under λ=0.95."""
    lam = 0.95
    early = (OriginDistanceObservation(turn=12, x=0, y=0, matched_planet_ids=(99,)),)
    late = (OriginDistanceObservation(turn=55, x=0, y=0, matched_planet_ids=(99,)),)
    selection = frozenset()  # miss → e = -log(ε) both
    e = -math.log(ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS)
    early_e = origin_distance_evidence_mean(early, selection, evidence_lambda=lam)
    late_e = origin_distance_evidence_mean(late, selection, evidence_lambda=lam)
    w12 = lam**12
    w55 = lam**55
    assert early_e == pytest.approx((w12 * e) / (1.0 + w12))
    assert late_e == pytest.approx((w55 * e) / (1.0 + w55))
    assert late_e < early_e


def test_ambiguous_match_set_prefers_covering_selection() -> None:
    """Selecting a planet in M is cheaper than selecting neither."""
    observations = (OriginDistanceObservation(turn=12, x=50, y=60, matched_planet_ids=(435, 483)),)
    covering = origin_distance_evidence_mean(observations, frozenset({435}), evidence_lambda=0.95)
    neither = origin_distance_evidence_mean(observations, frozenset({999}), evidence_lambda=0.95)
    assert covering < neither


def test_two_location_observations_cheaper_when_both_covered() -> None:
    """Two co-turn locations: covering both M sets beats covering one."""
    observations = (
        OriginDistanceObservation(turn=12, x=100, y=200, matched_planet_ids=(10,)),
        OriginDistanceObservation(turn=12, x=300, y=400, matched_planet_ids=(20,)),
    )
    both = origin_distance_evidence_mean(observations, frozenset({10, 20}), evidence_lambda=0.95)
    one = origin_distance_evidence_mean(observations, frozenset({10}), evidence_lambda=0.95)
    neither = origin_distance_evidence_mean(observations, frozenset({99}), evidence_lambda=0.95)
    assert both < one < neither
    # Same-turn mean: one miss of two obs → mean((-log 1 + -log ε)/2)
    w12 = 0.95**12
    expected_one = (
        0.0
        + w12
        * ((-math.log(1.0) + -math.log(ORIGIN_DISTANCE_EVIDENCE_EMPTY_INTERSECTION_EPS)) / 2.0)
    ) / (1.0 + w12)
    assert one == pytest.approx(expected_one)


def test_layout_prior_problem_from_materialized_view_retains_soft_evidence_observations(
    persistence,
    sample_turn,
    template_planet,
) -> None:
    """Regression: soft evidence must survive view → try_layout_prior_problem.

    Diagnostics for 663307 built a layout-prior problem from the materialized
    candidate view without re-passing aggregate observations. When omitted,
    observations were coerced to ``()``, so ``evidence_mean`` was always 0 and
    soft origin-distance scoring was silently disabled.
    """
    from dataclasses import replace

    from api.analytics.homeworld_locator.baseline_ensure import (
        materialize_homeworld_candidate_view,
    )
    from api.analytics.homeworld_locator.layout_prior import try_layout_prior_problem
    from api.analytics.homeworld_locator.layout_prior_cost import origin_distance_evidence_mean
    from api.analytics.homeworld_locator.models import CONFIDENCE_DEFINITE, CONFIDENCE_POSSIBLE
    from api.analytics.homeworld_locator.types import (
        HomeworldCandidateRecord,
        HomeworldEvidenceAggregate,
        HomeworldLocatorGameState,
    )
    from api.concepts.homeworld_layout import homeworld_settings_fingerprint

    from tests.test_homeworld_layout_prior import (
        _eligible_turn,
        _materialize_ctx,
        _planet,
        _stub_layout_asset,
        core_services,
    )
    from tests.test_homeworld_location_evidence import _ship

    turn, _pin = _eligible_turn(sample_turn, template_planet)
    center = (2000.0, 2000.0)
    player_count = 11
    radius = 550
    pin_angle = 0.0
    orphan_angle = 5.0 * 2.0 * math.pi / player_count
    pin_planet = _planet(
        template_planet,
        planet_id=1,
        x=int(center[0] + radius * math.cos(pin_angle)),
        y=int(center[1] + radius * math.sin(pin_angle)),
        ownerid=1,
    )
    orphan = _planet(
        template_planet,
        planet_id=2,
        x=int(center[0] + radius * math.cos(orphan_angle)),
        y=int(center[1] + radius * math.sin(orphan_angle)),
    )
    ship = _ship(
        turn.ships[0] if turn.ships else sample_turn.ships[0],
        ship_id=99,
        x=pin_planet.x,
        y=pin_planet.y,
        ownerid=turn.player.id,
    )
    turn = replace(
        turn,
        settings=replace(turn.settings, planetscanrange=80),
        planets=[pin_planet, orphan],
        ships=[ship],
    )
    observations = (
        OriginDistanceObservation(
            turn=1,
            x=orphan.x + 81,
            y=orphan.y,
            matched_planet_ids=(orphan.id,),
        ),
    )
    services = core_services(persistence, {1: turn})
    persistence.put_baseline(
        628580,
        1,
        HomeworldLocatorGameState(
            candidates=(
                HomeworldCandidateRecord(
                    planet_id=pin_planet.id,
                    perspective=1,
                    confidence_tier=CONFIDENCE_DEFINITE,
                ),
                HomeworldCandidateRecord(
                    planet_id=orphan.id,
                    perspective=None,
                    confidence_tier=CONFIDENCE_POSSIBLE,
                ),
            ),
            baseline_turn=1,
            baseline_degraded=False,
            settings_fingerprint=homeworld_settings_fingerprint(turn.settings),
            baseline_algorithm_version=HOMEWORLD_BASELINE_ALGORITHM_VERSION,
        ),
        HomeworldEvidenceAggregate(
            turn=1,
            baseline_turn=1,
            origin_distance_observations=observations,
            evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
        ),
    )

    ctx = _materialize_ctx(services, turn)
    view = materialize_homeworld_candidate_view(ctx, shell_turn=turn)
    assert view.available

    # Probe/diagnostics path: rebuild problem from the view without re-supplying
    # observations from the evidence aggregate.
    problem = try_layout_prior_problem(
        view.candidates,
        turn=turn,
        view=view,
        layout_asset=_stub_layout_asset(),
        map_center=center,
    )
    assert problem is not None
    assert problem.origin_distance_observations == observations
    assert (
        origin_distance_evidence_mean(
            problem.origin_distance_observations,
            frozenset({orphan.id}),
            evidence_lambda=problem.origin_distance_evidence_lambda,
        )
        == 0.0
    )
    assert (
        origin_distance_evidence_mean(
            problem.origin_distance_observations,
            frozenset(),
            evidence_lambda=problem.origin_distance_evidence_lambda,
        )
        > 0.0
    )
