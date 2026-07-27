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
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.evidence_refine import (
    cull_definite_neighborhood_candidates,
    materialize_evidence_adjusted_candidates,
)
from api.analytics.homeworld_locator.exports import EXPORT_CATALOG
from api.analytics.homeworld_locator.models import (
    CONFIDENCE_DEFINITE,
    CONFIDENCE_POSSIBLE,
    HomeworldIndependentEvidenceHit,
    HomeworldSingleStarbasePromotion,
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
from tests.test_homeworld_locator_core import _services

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
    )


def _floor_aggregate() -> HomeworldEvidenceAggregate:
    return HomeworldEvidenceAggregate(turn=1, baseline_turn=1)


def test_export_catalog_declares_self_chain() -> None:
    assert EXPORT_CATALOG.ensure_dependencies == (
        EnsureDependency(analytic_id=ANALYTIC_ID, turn_delta=-1, player_id="same"),
    )


def test_refine_accumulates_independent_hits_across_turns(persistence) -> None:
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
        export_services={ANALYTIC_ID: services},
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=3))
    aggregate = persistence.get_evidence_aggregate(628580, 1, 3)
    assert aggregate is not None
    assert aggregate.turn == 3
    assert aggregate.evidence_hits == ()


def test_refine_records_origin_distance_hit_on_shell_turn(persistence) -> None:
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
        export_services={ANALYTIC_ID: services},
    ).exports
    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=2))
    aggregate = persistence.get_evidence_aggregate(628580, 1, 2)
    assert aggregate is not None
    assert aggregate.turn == 2
    assert aggregate.evidence_hits == (HomeworldIndependentEvidenceHit(planet_id=10, turn=2),)


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
        export_services={ANALYTIC_ID: services},
    ).exports

    assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=4))
    assert persistence.get_evidence_aggregate(628580, 1, 2) is not None
    assert persistence.get_evidence_aggregate(628580, 1, 3) is not None
    assert persistence.get_evidence_aggregate(628580, 1, 4) is not None


def test_threshold_promotion_materializes_definite(persistence) -> None:
    turn = _load_turn()
    aggregate = HomeworldEvidenceAggregate(
        turn=5,
        baseline_turn=1,
        evidence_hits=(
            HomeworldIndependentEvidenceHit(planet_id=10, turn=2),
            HomeworldIndependentEvidenceHit(planet_id=10, turn=3),
        ),
    )
    candidates = materialize_evidence_adjusted_candidates(
        (_candidate(10),),
        aggregate,
        planets=turn.planets,
        settings_turn=turn,
        player_count=11,
        promotion_threshold=2,
    )
    assert candidates[0].confidence_tier == CONFIDENCE_DEFINITE


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
        promotion_threshold=2,
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
        promotion_threshold=2,
    )
    assert [row.planet_id for row in candidates] == [1, 2]


def test_run_homeworld_refine_persist_round_trip(persistence) -> None:
    from api.analytics.compute_context import make_analytic_compute_context

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    services = _services(persistence, {1: turn_one, 2: turn_two})
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    ctx = make_analytic_compute_context(
        turn_two,
        load_turn=lambda n: {1: turn_one, 2: turn_two}.get(n),
        export_services={ANALYTIC_ID: services},
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
        export_services={ANALYTIC_ID: services},
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
