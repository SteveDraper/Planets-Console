"""Tests for soft origin-distance freeze at shared ship limit."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.homeworld_locator.evidence_refine import refine_homeworld_evidence_aggregate
from api.analytics.homeworld_locator.models import OriginDistanceObservation
from api.analytics.homeworld_locator.origin_distance_evidence_policy import (
    effective_origin_distance_observations,
    first_shared_ship_limit_turn,
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
from api.errors import ValidationError
from api.models.game import TurnInfo
from api.serialization.turn import turn_info_from_json

from tests.test_homeworld_location_evidence import _planet, _ship

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _load_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


def _scoreboard_turns(
    template: TurnInfo,
    *,
    through: int,
    first_over_limit_turn: int,
) -> dict[int, TurnInfo]:
    """Turns ``1..through`` whose shared ship limit is crossed at ``first_over_limit_turn``."""
    total = total_reported_ships(template.scores)
    over_limit = max(1, total)
    under_limit = total + 1
    return {
        turn_number: replace(
            template,
            settings=replace(
                template.settings,
                turn=turn_number,
                shiplimit=over_limit if turn_number >= first_over_limit_turn else under_limit,
                acceleratedturns=0,
            ),
            # Keep score.turn aligned with settings.turn so the shared ship-limit
            # helper's current-turn filter still sees these rows.
            scores=tuple(replace(score, turn=turn_number) for score in template.scores),
            ships=[],
        )
        for turn_number in range(1, through + 1)
    }


def _turn_loader(turns: Mapping[int, TurnInfo]) -> Callable[[int], TurnInfo | None]:
    """``load_turn`` over an explicit scoreboard map; turns outside it load as None."""
    return lambda turn_number: turns.get(turn_number)


def _rejecting_turn_loader() -> Callable[[int], TurnInfo | None]:
    """``load_turn`` that fails the test if the freeze policy reads scoreboard turns."""

    def load_turn(turn_number: int) -> TurnInfo | None:
        raise AssertionError(f"unexpected scoreboard load of turn {turn_number}")

    return load_turn


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


def test_shared_ship_limit_ignores_non_current_turn_score_rows() -> None:
    turn = _load_turn()
    current_total = total_reported_ships(
        [score for score in turn.scores if score.turn == turn.settings.turn]
    )
    stale = tuple(
        replace(
            score,
            turn=turn.settings.turn - 1,
            capitalships=score.capitalships + 10_000,
            freighters=score.freighters + 10_000,
        )
        for score in turn.scores
    )
    mixed = tuple(turn.scores) + stale
    over = replace(turn.settings, shiplimit=max(1, current_total))
    under = replace(turn.settings, shiplimit=current_total + 1)
    assert is_at_or_over_shared_ship_limit(over, mixed) is True
    assert is_at_or_over_shared_ship_limit(under, mixed) is False
    # Without the current-turn filter, stale rows alone would trip an under-limit gate.
    assert total_reported_ships(mixed) > under.shiplimit


def test_resolve_through_turn_sticky_on_first_limit_hit() -> None:
    turns = _scoreboard_turns(_load_turn(), through=24, first_over_limit_turn=24)
    prior = HomeworldEvidenceAggregate(turn=23, baseline_turn=1)
    assert (
        resolve_origin_distance_evidence_through_turn(
            prior,
            turn=turns[24],
            load_turn=_turn_loader(turns),
        )
        == 23
    )


def test_resolve_through_turn_keeps_frozen_cutoff_without_loading() -> None:
    turns = _scoreboard_turns(_load_turn(), through=60, first_over_limit_turn=24)
    frozen = HomeworldEvidenceAggregate(
        turn=59,
        baseline_turn=1,
        origin_distance_evidence_through_turn=23,
    )
    assert (
        resolve_origin_distance_evidence_through_turn(
            frozen,
            turn=turns[60],
            load_turn=_rejecting_turn_loader(),
        )
        == 23
    )


def test_resolve_through_turn_uses_earliest_historical_crossing() -> None:
    turns = _scoreboard_turns(_load_turn(), through=60, first_over_limit_turn=24)
    loaded_turns: list[int] = []

    def load_turn(turn_number: int) -> TurnInfo | None:
        loaded_turns.append(turn_number)
        return turns.get(turn_number)

    prior = HomeworldEvidenceAggregate(turn=59, baseline_turn=1)
    assert (
        resolve_origin_distance_evidence_through_turn(
            prior,
            turn=turns[60],
            load_turn=load_turn,
        )
        == 23
    )
    assert max(loaded_turns) == 24


def test_resolve_through_turn_under_limit_leaves_unset() -> None:
    turns = _scoreboard_turns(_load_turn(), through=24, first_over_limit_turn=99)
    prior = HomeworldEvidenceAggregate(turn=23, baseline_turn=1)
    assert (
        resolve_origin_distance_evidence_through_turn(
            prior,
            turn=turns[24],
            load_turn=_rejecting_turn_loader(),
        )
        is None
    )


def test_first_shared_ship_limit_turn_raises_on_missing_turn() -> None:
    turns = _scoreboard_turns(_load_turn(), through=5, first_over_limit_turn=5)
    shell = turns[5]
    del turns[3]

    with pytest.raises(ValidationError, match="scoreboard history turn 3"):
        first_shared_ship_limit_turn(shell_turn=shell, load_turn=_turn_loader(turns))


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
    sample = _load_turn()
    candidate = _planet(sample.planets[0], planet_id=10, x=100, y=100)
    ship = _ship(
        sample.ships[0],
        ship_id=1,
        x=candidate.x + 81,
        y=candidate.y,
        ownerid=sample.player.id + 1,
    )
    turns = _scoreboard_turns(sample, through=24, first_over_limit_turn=24)
    shell = replace(
        turns[24],
        settings=replace(turns[24].settings, planetscanrange=300),
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
        turn=shell,
        candidate_planet_ids_set=frozenset({10}),
        planets_by_id={10: candidate},
        load_turn=_turn_loader(turns),
    )
    assert result.aggregate.origin_distance_evidence_through_turn == 23
    assert all(o.turn <= 23 for o in result.aggregate.origin_distance_observations)
    assert not any(o.turn == 24 for o in result.aggregate.origin_distance_observations)
    # Freeze drops the post-cutoff prior observation; nothing new is appended.
    assert result.counts.observations_dropped_by_freeze == 1
    assert result.counts.new_observations_appended == 0


def test_refine_counts_appended_observations_before_freeze() -> None:
    sample = _load_turn()
    candidate = _planet(sample.planets[0], planet_id=10, x=100, y=100)
    ship = _ship(
        sample.ships[0],
        ship_id=1,
        x=candidate.x + 81,
        y=candidate.y,
        ownerid=sample.player.id + 1,
    )
    turns = _scoreboard_turns(sample, through=24, first_over_limit_turn=99)
    shell = replace(
        turns[24],
        settings=replace(turns[24].settings, planetscanrange=300),
        planets=[candidate],
        ships=[ship],
    )
    prior = HomeworldEvidenceAggregate(
        turn=23,
        baseline_turn=1,
        origin_distance_observations=(
            OriginDistanceObservation(turn=10, x=0, y=0, matched_planet_ids=(10,)),
        ),
    )
    result = refine_homeworld_evidence_aggregate(
        prior,
        turn=shell,
        candidate_planet_ids_set=frozenset({10}),
        planets_by_id={10: candidate},
        load_turn=_turn_loader(turns),
    )
    assert result.aggregate.origin_distance_evidence_through_turn is None
    assert result.counts.origin_distance_matches == 1
    assert result.counts.observations_dropped_by_freeze == 0
    assert result.counts.new_observations_appended == 1
    assert result.counts.prior_observation_count == 1


def test_refine_freeze_cutoff_from_earlier_historical_crossing() -> None:
    sample = _load_turn()
    candidate = _planet(sample.planets[0], planet_id=10, x=100, y=100)
    turns = _scoreboard_turns(sample, through=60, first_over_limit_turn=24)
    shell = replace(turns[60], planets=[candidate])
    prior = HomeworldEvidenceAggregate(
        turn=59,
        baseline_turn=1,
        origin_distance_observations=(
            OriginDistanceObservation(turn=10, x=0, y=0, matched_planet_ids=(10,)),
            OriginDistanceObservation(turn=30, x=9, y=9, matched_planet_ids=(10,)),
            OriginDistanceObservation(turn=50, x=8, y=8, matched_planet_ids=(10,)),
        ),
    )
    result = refine_homeworld_evidence_aggregate(
        prior,
        turn=shell,
        candidate_planet_ids_set=frozenset({10}),
        planets_by_id={10: candidate},
        load_turn=_turn_loader(turns),
    )
    assert result.aggregate.origin_distance_evidence_through_turn == 23
    assert all(o.turn <= 23 for o in result.aggregate.origin_distance_observations)


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


def test_ensure_refine_freeze_cutoff_walks_scoreboard_turns() -> None:
    """Ensure path resolves the freeze via services.load_turn at the earliest crossing."""
    from api.analytics.homeworld_locator.evidence_ensure import (
        compute_homeworld_evidence_refine_step_detailed,
    )
    from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
    from api.analytics.homeworld_locator.types import (
        HomeworldLocatorGameState,
    )
    from api.concepts.homeworld_layout import homeworld_settings_fingerprint
    from api.storage.memory_asset import MemoryAssetBackend

    from tests.test_homeworld_location_evidence import _candidate
    from tests.test_homeworld_locator_core import _services

    turns = _scoreboard_turns(_load_turn(), through=5, first_over_limit_turn=3)
    shell = turns[5]
    persistence = HomeworldLocatorPersistenceService(MemoryAssetBackend(initial={}))
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        HomeworldLocatorGameState(
            candidates=(_candidate(10),),
            baseline_turn=1,
            baseline_degraded=False,
            settings_fingerprint=homeworld_settings_fingerprint(shell.settings),
        ),
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1),
    )
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(
            turn=4,
            baseline_turn=1,
            origin_distance_observations=(
                OriginDistanceObservation(turn=2, x=0, y=0, matched_planet_ids=(10,)),
                OriginDistanceObservation(turn=4, x=1, y=1, matched_planet_ids=(10,)),
            ),
        ),
    )

    step = compute_homeworld_evidence_refine_step_detailed(services, turn=shell)
    assert step.computed is True
    assert step.aggregate.origin_distance_evidence_through_turn == 2
    assert all(o.turn <= 2 for o in step.aggregate.origin_distance_observations)
