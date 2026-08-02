"""Core tests for homeworld evidence refine, materialize, and orchestrator chain."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.export_types import EnsureDependency
from api.analytics.homeworld_locator.baseline_ensure import materialize_homeworld_candidate_view
from api.analytics.homeworld_locator.compute_orchestration import (
    HomeworldLocatorPersistencePolicy,
    build_homeworld_refine_job_wire,
    run_homeworld_refine,
)
from api.analytics.homeworld_locator.constants import (
    ANALYTIC_ID,
    HOMEWORLD_BASELINE_ALGORITHM_VERSION,
)
from api.analytics.homeworld_locator.evidence_refine import (
    cull_definite_neighborhood_candidates,
    materialize_evidence_adjusted_candidates,
)
from api.analytics.homeworld_locator.exports import EXPORT_CATALOG
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    HomeworldSingleStarbasePromotion,
    OriginDistanceObservation,
)
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.homeworld_locator.types import (
    HomeworldCandidateRecord,
    HomeworldEvidenceAggregate,
    HomeworldLocatorGameState,
)
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs
from api.concepts.homeworld_layout import homeworld_settings_fingerprint
from api.concepts.planet_connections.wells import max_travel_distance
from api.models.planet import Planet
from api.serialization.turn import turn_info_from_json
from api.storage.memory_asset import MemoryAssetBackend

from tests.test_homeworld_location_evidence import (
    _candidate,
    _planet,
    _ship,
    _turn_with_owner_starbase_count,
)
from tests.test_homeworld_locator_core import _export_services, _services

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    return MemoryAssetBackend(initial={})


@pytest.fixture
def persistence(memory_backend):
    return HomeworldLocatorPersistenceService(memory_backend)


def _load_turn():
    raw = json.loads((ASSETS_DIR / "turn_sample.json").read_text(encoding="utf-8"))
    return turn_info_from_json(raw, settings_defaults=raw["settings"])


def _baseline_state(
    turn_settings,
    *candidates: HomeworldCandidateRecord,
) -> HomeworldLocatorGameState:
    return HomeworldLocatorGameState(
        candidates=candidates,
        baseline_turn=1,
        baseline_degraded=False,
        settings_fingerprint=homeworld_settings_fingerprint(turn_settings),
        baseline_algorithm_version=HOMEWORLD_BASELINE_ALGORITHM_VERSION,
    )


def _floor_aggregate() -> HomeworldEvidenceAggregate:
    return HomeworldEvidenceAggregate(turn=1, baseline_turn=1)


def test_export_catalog_declares_self_chain() -> None:
    assert EXPORT_CATALOG.ensure_dependencies == (
        EnsureDependency(analytic_id=ANALYTIC_ID, turn_delta=-1, player_id="same"),
        EnsureDependency(analytic_id="fleet", turn_delta=0, player_id="all", quality="final"),
    )


def test_refine_accumulates_empty_observations_across_turns(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    turn_three = replace(turn_one, settings=replace(turn_one.settings, turn=3))
    turns = {1: turn_one, 2: turn_two, 3: turn_three}
    services = _services(persistence, turns)

    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_three,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=3))
    aggregate = persistence.get_evidence_aggregate(628580, 1, 3)
    assert aggregate is not None
    assert aggregate.turn == 3
    assert aggregate.origin_distance_observations == ()


def test_refine_records_origin_distance_observation_on_shell_turn(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    ship_template = turn_two.ships[0]
    hw_planet = _planet(turn_two.planets[0], planet_id=10, x=500, y=500)
    warp8 = max_travel_distance(8, False)
    ship = _ship(ship_template, ship_id=99, x=500 + int(warp8), y=500)
    turn_two = replace(turn_two, planets=[hw_planet], ships=[ship])
    turns = {1: turn_one, 2: turn_two}

    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_two,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=2))
    aggregate = persistence.get_evidence_aggregate(628580, 1, 2)
    assert aggregate is not None
    assert aggregate.turn == 2
    assert aggregate.origin_distance_observations == (
        OriginDistanceObservation(
            turn=2,
            x=ship.x,
            y=ship.y,
            matched_planet_ids=(10,),
        ),
    )


def test_refine_dedupes_colocated_ships_and_keeps_distinct_locations(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    ship_template = turn_two.ships[0]
    planet_a = _planet(turn_two.planets[0], planet_id=10, x=500, y=500)
    warp8 = max_travel_distance(8, False)
    loc1_x = 500 + int(warp8)
    loc1_y = 500
    loc2_x = 500
    loc2_y = 500 + int(warp8)
    ships = [
        _ship(ship_template, ship_id=1, x=loc1_x, y=loc1_y),
        _ship(ship_template, ship_id=2, x=loc1_x, y=loc1_y),
        _ship(ship_template, ship_id=3, x=loc2_x, y=loc2_y),
    ]
    turn_two = replace(turn_two, planets=[planet_a], ships=ships)
    turns = {1: turn_one, 2: turn_two}

    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_two,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=2))
    aggregate = persistence.get_evidence_aggregate(628580, 1, 2)
    assert aggregate is not None
    assert aggregate.origin_distance_observations == (
        OriginDistanceObservation(
            turn=2,
            x=loc1_x,
            y=loc1_y,
            matched_planet_ids=(10,),
        ),
        OriginDistanceObservation(
            turn=2,
            x=loc2_x,
            y=loc2_y,
            matched_planet_ids=(10,),
        ),
    )


def test_refine_records_ambiguous_match_set(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    ship_template = turn_two.ships[0]
    # Two candidates at the same origin-distance band from one ship location.
    planet_a = _planet(turn_two.planets[0], planet_id=435, x=500, y=500)
    planet_b = _planet(turn_two.planets[0], planet_id=483, x=500, y=500)
    warp8 = max_travel_distance(8, False)
    ship = _ship(ship_template, ship_id=99, x=500 + int(warp8), y=500)
    turn_two = replace(turn_two, planets=[planet_a, planet_b], ships=[ship])
    turns = {1: turn_one, 2: turn_two}

    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(435), _candidate(483)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_two,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=2))
    aggregate = persistence.get_evidence_aggregate(628580, 1, 2)
    assert aggregate is not None
    assert aggregate.origin_distance_observations == (
        OriginDistanceObservation(
            turn=2,
            x=ship.x,
            y=ship.y,
            matched_planet_ids=(435, 483),
        ),
    )
    assert len(aggregate.origin_distance_observations[0].matched_planet_ids) == 2


def test_single_step_refine_requires_prior_when_above_ensure_floor(persistence) -> None:
    """Above the accelerated ensure floor, refine is one step and needs T-1."""
    from api.analytics.homeworld_locator.evidence_ensure import ensure_homeworld_evidence_refined
    from api.errors import ValidationError

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    # acceleratedturns=3 in sample: floor is 3 for scope>=3, so turn 4 needs prior@3.
    turn_four = replace(
        turn_one,
        settings=replace(turn_one.settings, turn=4, acceleratedturns=3),
    )
    services = _services(persistence, {1: turn_one, 4: turn_four})
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    with pytest.raises(ValidationError, match="before turn 4"):
        ensure_homeworld_evidence_refined(
            services,
            shell_turn=turn_four,
            game_state_baseline_turn=1,
        )


def test_export_ensure_raises_on_missing_intermediate_turn(persistence) -> None:
    """Sparse stores must fail with an explicit missing-turn ValidationError."""
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.evidence_refine_timing_history import (
        clear_ensure_failure_reports,
        recent_ensure_failure_reports,
    )
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export
    from api.errors import ValidationError
    from api.services.layout_prior_diagnostics_service import get_layout_prior_reports_wire

    clear_ensure_failure_reports()
    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    turn_three = replace(turn_one, settings=replace(turn_one.settings, turn=3))
    # Hole at turn 2 -- same shape as 663307 missing 59 with 58 and 60 present.
    turns = {1: turn_one, 3: turn_three}
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_three,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    with pytest.raises(ValidationError, match="sign in to auto-fetch"):
        ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=3))

    failures = recent_ensure_failure_reports(game_id=628580, perspective=1)
    assert len(failures) == 1
    assert failures[0].missing_turn == 2
    assert failures[0].shell_turn == 3
    wire = get_layout_prior_reports_wire(game_id=628580, perspective=1, turn=3)
    assert wire["ensureFailures"][0]["missingTurn"] == 2


def test_export_ensure_autofetches_missing_intermediate_turns(persistence) -> None:
    """Login-backed ensure_turn fills holes so the evidence chain can continue."""
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    turn_three = replace(turn_one, settings=replace(turn_one.settings, turn=3))
    turns = {1: turn_one, 3: turn_three}
    ensure_calls: list[int] = []

    def ensure_turn(turn_number: int):
        ensure_calls.append(turn_number)
        if turn_number == 2:
            turns[2] = turn_two
            return turn_two
        return None

    services = _services(persistence, turns, ensure_turn=ensure_turn)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_three,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=3))
    assert ensure_calls == [2]
    assert persistence.get_evidence_aggregate(628580, 1, 3) is not None


def test_export_ensure_reports_fetch_failure_after_partial_autofetch(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.evidence_refine_timing_history import (
        clear_ensure_failure_reports,
        recent_ensure_failure_reports,
    )
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export
    from api.errors import ValidationError

    clear_ensure_failure_reports()
    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    turn_four = replace(turn_one, settings=replace(turn_one.settings, turn=4))
    turns = {1: turn_one, 4: turn_four}

    def ensure_turn(turn_number: int):
        if turn_number == 2:
            turns[2] = turn_two
            return turn_two
        return None  # turn 3 fetch fails

    services = _services(persistence, turns, ensure_turn=ensure_turn)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )
    ctx = make_analytic_compute_context(
        turn_four,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    with pytest.raises(ValidationError, match="could not load turn 3"):
        ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=4))
    failures = recent_ensure_failure_reports(game_id=628580, perspective=1)
    assert failures[0].reason == "turn_fetch_failed"
    assert failures[0].missing_turn == 3


def test_export_ensure_gap_fill_walks_dependencies(persistence) -> None:
    """Gap-fill creates intermediate aggregates via ENSURE_DEPENDENCIES, not a private loop."""
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    turns = {
        1: turn_one,
        2: replace(turn_one, settings=replace(turn_one.settings, turn=2)),
        3: replace(turn_one, settings=replace(turn_one.settings, turn=3)),
        4: replace(turn_one, settings=replace(turn_one.settings, turn=4)),
    }
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )
    ctx = make_analytic_compute_context(
        turns[4],
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports

    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=4))
    assert persistence.get_evidence_aggregate(628580, 1, 2) is not None
    assert persistence.get_evidence_aggregate(628580, 1, 3) is not None
    assert persistence.get_evidence_aggregate(628580, 1, 4) is not None


def test_export_ensure_delegates_the_ensure_loop_to_the_framework(persistence) -> None:
    """Dependency ensure runs through ``ensure_declared_dependencies``, not a local loop."""
    from unittest.mock import patch

    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_context import AnalyticQueryContext
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    turns = {
        1: turn_one,
        2: replace(turn_one, settings=replace(turn_one.settings, turn=2)),
        3: replace(turn_one, settings=replace(turn_one.settings, turn=3)),
    }
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )
    ctx = make_analytic_compute_context(
        turns[3],
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports

    original_ensure_declared = AnalyticQueryContext.ensure_declared_dependencies
    ensured_scopes: list[tuple[str, int]] = []

    def tracking_ensure_declared_dependencies(self, analytic_id, scope):
        ensured_scopes.append((analytic_id, scope.turn))
        return original_ensure_declared(self, analytic_id, scope)

    with patch.object(
        AnalyticQueryContext,
        "ensure_declared_dependencies",
        tracking_ensure_declared_dependencies,
    ):
        assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=3))

    assert ensured_scopes == [(ANALYTIC_ID, 3), (ANALYTIC_ID, 2)]
    assert persistence.get_evidence_aggregate(628580, 1, 3) is not None


def test_export_ensure_ignores_holes_below_an_already_refined_prior_turn(persistence) -> None:
    """A hole the walk never needs must not fail the shell turn or trigger auto-fetch."""
    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export

    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    # Hole at turn 2, but evidence is already refined through turn 3.
    turns = {
        1: turn_one,
        3: replace(turn_one, settings=replace(turn_one.settings, turn=3)),
        4: replace(turn_one, settings=replace(turn_one.settings, turn=4)),
    }
    fetch_calls: list[int] = []

    def ensure_turn(turn_number: int):
        fetch_calls.append(turn_number)
        return None

    services = _services(persistence, turns, ensure_turn=ensure_turn)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(turn=3, baseline_turn=1),
    )
    ctx = make_analytic_compute_context(
        turns[4],
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports

    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=4))
    assert fetch_calls == []
    assert persistence.get_evidence_aggregate(628580, 1, 4) is not None


def test_origin_distance_observations_do_not_promote_to_definite() -> None:
    turn = _load_turn()
    aggregate = HomeworldEvidenceAggregate(
        turn=5,
        baseline_turn=1,
        origin_distance_observations=(
            OriginDistanceObservation(turn=2, x=100, y=200, matched_planet_ids=(10,)),
            OriginDistanceObservation(turn=3, x=110, y=210, matched_planet_ids=(10,)),
        ),
    )
    candidates = materialize_evidence_adjusted_candidates(
        (_candidate(10),),
        aggregate,
        planets=turn.planets,
        settings_turn=turn,
        player_count=11,
    )
    assert candidates[0].confidence_tier == CONFIDENCE_POSSIBLE


def test_single_starbase_promotion_materializes_without_owner_assignment() -> None:
    turn = _load_turn()
    orphan = _candidate(10, perspective=None)
    aggregate = HomeworldEvidenceAggregate(
        turn=5,
        baseline_turn=1,
        single_starbase_promotions=(HomeworldSingleStarbasePromotion(planet_id=10, turn=5),),
    )
    candidates = materialize_evidence_adjusted_candidates(
        (orphan,),
        aggregate,
        planets=turn.planets,
        settings_turn=turn,
        player_count=11,
    )
    assert candidates[0].confidence_tier == CONFIDENCE_DEFINITE
    assert candidates[0].perspective is None


def test_definite_neighborhood_cull_uses_support_min(template_planet) -> None:
    definite = _planet(template_planet, planet_id=1, x=0, y=0)
    too_close = _planet(template_planet, planet_id=2, x=100, y=0)
    far_enough = _planet(template_planet, planet_id=3, x=500, y=0)
    planets_by_id = {1: definite, 2: too_close, 3: far_enough}
    candidates = (
        HomeworldCandidateRecord(planet_id=1, perspective=1, confidence_tier=CONFIDENCE_DEFINITE),
        HomeworldCandidateRecord(
            planet_id=2, perspective=None, confidence_tier=CONFIDENCE_POSSIBLE
        ),
        HomeworldCandidateRecord(
            planet_id=3, perspective=None, confidence_tier=CONFIDENCE_POSSIBLE
        ),
    )
    culled = cull_definite_neighborhood_candidates(
        candidates,
        planets_by_id,
        min_separation_ly=430.0,
    )
    assert [row.planet_id for row in culled] == [1, 3]


def test_neighborhood_cull_skipped_when_layout_ineligible(template_planet, sample_settings) -> None:
    from api.concepts.homeworld_layout import HW_DISTRIBUTION_RANDOM_SPACED

    turn = replace(
        _load_turn(),
        settings=replace(
            sample_settings,
            hwdistribution=HW_DISTRIBUTION_RANDOM_SPACED,
            turn=5,
        ),
    )
    definite = _planet(template_planet, planet_id=1, x=0, y=0)
    nearby = _planet(template_planet, planet_id=2, x=50, y=0)
    aggregate = HomeworldEvidenceAggregate(turn=5, baseline_turn=1)
    candidates = materialize_evidence_adjusted_candidates(
        (
            HomeworldCandidateRecord(
                planet_id=1, perspective=1, confidence_tier=CONFIDENCE_DEFINITE
            ),
            HomeworldCandidateRecord(
                planet_id=2, perspective=None, confidence_tier=CONFIDENCE_POSSIBLE
            ),
        ),
        aggregate,
        planets=[definite, nearby],
        settings_turn=turn,
        player_count=11,
    )
    assert [row.planet_id for row in candidates] == [1, 2]


def test_run_homeworld_refine_persist_round_trip(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    turns = {1: turn_one, 2: turn_two}
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_two,
        load_turn=lambda n: {1: turn_one, 2: turn_two}.get(n),
        export_services=_export_services(services, turns),
    ).exports
    scope = ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
    )
    job_wire = build_homeworld_refine_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )
    result = run_homeworld_refine(job_wire)
    assert result.outcome == "persist"
    assert persistence.get_evidence_aggregate(628580, 1, 2) is None

    HomeworldLocatorPersistencePolicy().persist(ctx, scope, result.payload)
    stored = persistence.get_evidence_aggregate(628580, 1, 2)
    assert stored is not None
    assert stored.turn == 2
    assert stored.baseline_turn == 1


def test_materialize_view_refines_through_shell_turn(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    turn_sb = _turn_with_owner_starbase_count(turn_two, owner_id=2, starbases=1)
    ship_template = turn_sb.ships[0]
    hw_planet = _planet(turn_sb.planets[0], planet_id=10, x=300, y=300)
    ship = _ship(ship_template, ship_id=99, x=300, y=300, ownerid=2, turn=1)
    turn_two = replace(turn_sb, planets=[hw_planet], ships=[ship])
    turns = {1: turn_one, 2: turn_two}

    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10, perspective=None)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_two,
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    view = materialize_homeworld_candidate_view(ctx, shell_turn=turn_two)
    assert view.candidates[0].confidence_tier == CONFIDENCE_DEFINITE
    assert view.candidates[0].perspective is None
    assert persistence.get_evidence_aggregate(628580, 1, 2) is not None


@pytest.fixture
def template_planet(sample_turn) -> Planet:
    return sample_turn.planets[0]


@pytest.fixture
def sample_settings(sample_turn):
    return sample_turn.settings


@pytest.fixture
def sample_turn():
    return _load_turn()
