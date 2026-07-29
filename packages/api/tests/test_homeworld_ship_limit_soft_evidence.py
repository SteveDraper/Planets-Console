"""Tests for soft origin-distance freeze at shared ship limit."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from api.analytics.homeworld_locator.evidence_refine import refine_homeworld_evidence_aggregate
from api.analytics.homeworld_locator.models import OriginDistanceObservation
from api.analytics.homeworld_locator.origin_distance_evidence_policy import (
    effective_origin_distance_observations,
    resolve_origin_distance_evidence_through_turn,
)
from api.analytics.homeworld_locator.serialization import (
    homeworld_evidence_aggregate_from_json,
    homeworld_evidence_aggregate_to_json,
)
from api.analytics.homeworld_locator.types import HomeworldEvidenceAggregate
from api.concepts.ship_limit import (
    is_at_or_over_shared_ship_limit,
    total_reported_ships,
)
from api.serialization.turn import turn_info_from_json

from tests.test_homeworld_location_evidence import _planet, _ship

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _load_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


def test_shared_ship_limit_uses_scoreboard_total() -> None:
    turn = _load_turn()
    total = total_reported_ships(turn.scores)
    assert is_at_or_over_shared_ship_limit(turn.settings, turn.scores) is (
        total >= turn.settings.shiplimit
    )
    over = replace(turn.settings, shiplimit=max(1, total))
    assert is_at_or_over_shared_ship_limit(over, turn.scores) is True
    under = replace(turn.settings, shiplimit=total + 1)
    assert is_at_or_over_shared_ship_limit(under, turn.scores) is False


def test_resolve_through_turn_sticky_on_first_limit_hit() -> None:
    turn = _load_turn()
    turn = replace(turn, settings=replace(turn.settings, turn=24, shiplimit=1))
    prior = HomeworldEvidenceAggregate(turn=23, baseline_turn=1)
    assert resolve_origin_distance_evidence_through_turn(prior, turn=turn) == 23

    frozen = HomeworldEvidenceAggregate(
        turn=24,
        baseline_turn=1,
        origin_distance_evidence_through_turn=23,
    )
    later = replace(turn, settings=replace(turn.settings, turn=60, shiplimit=1))
    assert resolve_origin_distance_evidence_through_turn(frozen, turn=later) == 23


def test_effective_observations_honor_through_turn() -> None:
    aggregate = HomeworldEvidenceAggregate(
        turn=30,
        baseline_turn=1,
        origin_distance_observations=(
            OriginDistanceObservation(turn=10, x=1, y=1, matched_planet_ids=(1,)),
            OriginDistanceObservation(turn=25, x=2, y=2, matched_planet_ids=(2,)),
        ),
        origin_distance_evidence_through_turn=23,
    )
    effective = effective_origin_distance_observations(aggregate)
    assert len(effective) == 1
    assert effective[0].turn == 10


def test_refine_stops_origin_distance_after_ship_limit() -> None:
    turn = _load_turn()
    template = turn.planets[0]
    candidate = _planet(template, planet_id=10, x=100, y=100)
    ship = _ship(
        turn.ships[0],
        ship_id=1,
        x=candidate.x + 81,
        y=candidate.y,
        ownerid=turn.player.id + 1,
    )
    # Force shared ship limit on this turn.
    turn = replace(
        turn,
        settings=replace(turn.settings, turn=24, shiplimit=1, planetscanrange=300),
        planets=[candidate],
        ships=[ship],
    )
    prior = HomeworldEvidenceAggregate(
        turn=23,
        baseline_turn=1,
        origin_distance_observations=(
            OriginDistanceObservation(turn=10, x=0, y=0, matched_planet_ids=(10,)),
            OriginDistanceObservation(turn=30, x=9, y=9, matched_planet_ids=(10,)),
        ),
    )
    result = refine_homeworld_evidence_aggregate(
        prior,
        turn=turn,
        candidate_planet_ids_set=frozenset({10}),
        planets_by_id={10: candidate},
    )
    assert result.aggregate.origin_distance_evidence_through_turn == 23
    assert all(o.turn <= 23 for o in result.aggregate.origin_distance_observations)
    assert not any(o.turn == 24 for o in result.aggregate.origin_distance_observations)
    assert result.counts.new_observations_appended <= 0


def test_evidence_through_turn_codec_round_trip() -> None:
    aggregate = HomeworldEvidenceAggregate(
        turn=24,
        baseline_turn=1,
        origin_distance_evidence_through_turn=23,
        origin_distance_observations=(
            OriginDistanceObservation(turn=12, x=1, y=2, matched_planet_ids=(5, 6)),
        ),
    )
    restored = homeworld_evidence_aggregate_from_json(
        homeworld_evidence_aggregate_to_json(aggregate)
    )
    assert restored.origin_distance_evidence_through_turn == 23
    assert restored.origin_distance_observations == aggregate.origin_distance_observations
