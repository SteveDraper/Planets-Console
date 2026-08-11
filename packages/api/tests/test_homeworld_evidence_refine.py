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
    HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
)
from api.analytics.homeworld_locator.evidence_refine import (
    apply_definite_keyed_candidate_culls,
    cull_definite_neighborhood_candidates,
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
    return HomeworldEvidenceAggregate(
        turn=1,
        baseline_turn=1,
        evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
    )


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
    from api.analytics.turn_roster import iter_turn_players

    from tests.test_homeworld_locator_core import _final_fleet_ledger

    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
    turn_two = replace(turn_one, settings=replace(turn_one.settings, turn=2))
    turn_three = replace(turn_one, settings=replace(turn_one.settings, turn=3))
    turns = {1: turn_one, 3: turn_three}
    ensure_calls: list[int] = []
    export_services: dict[str, object] = {}

    def ensure_turn(turn_number: int):
        ensure_calls.append(turn_number)
        if turn_number == 2:
            turns[2] = turn_two
            fleet_services = export_services["fleet"]
            for player in iter_turn_players(turn_two):
                fleet_services.persistence.put_ledger(
                    fleet_services.game_id,
                    fleet_services.perspective,
                    2,
                    player.id,
                    _final_fleet_ledger(player.id),
                )
            return turn_two
        return None

    services = _services(persistence, turns, ensure_turn=ensure_turn)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        _floor_aggregate(),
    )

    export_services.update(_export_services(services, turns))
    ctx = make_analytic_compute_context(
        turn_three,
        load_turn=lambda n: turns.get(n),
        export_services=export_services,
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


def test_export_ensure_prepares_chain_then_uses_orchestrator(persistence, monkeypatch) -> None:
    """Homeworld ensure fills turns via walk check, then submit+wait (no sync ensure loop)."""
    from unittest.mock import patch

    from api.analytics.compute_context import make_analytic_compute_context
    from api.analytics.export_context import AnalyticQueryContext
    from api.analytics.export_types import ExportScope
    from api.analytics.homeworld_locator.exports import ensure_homeworld_export
    from api.compute import export_ensure as export_ensure_module

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

    walk_scopes: list[tuple[str, int]] = []
    original_dependency_walk = AnalyticQueryContext.dependency_walk_unavailable

    def tracking_dependency_walk_unavailable(self, analytic_id, scope):
        walk_scopes.append((analytic_id, scope.turn))
        return original_dependency_walk(self, analytic_id, scope)

    orchestrator_calls: list[tuple[str, int]] = []

    def tracking_ensure_via_orchestrator(ctx, analytic_id, scope, **_kwargs):
        orchestrator_calls.append((analytic_id, scope.turn))
        # Satisfy via the sync refine path for this unit assertion (DAG unwind
        # would refine turns 1..shell; mirror that here).
        from api.analytics.homeworld_locator.baseline_ensure import ensure_homeworld_baseline
        from api.analytics.homeworld_locator.compute_services import resolve_homeworld_services
        from api.analytics.homeworld_locator.evidence_ensure import (
            ensure_homeworld_evidence_refined,
        )
        from api.analytics.homeworld_locator.exports import _fleet_built_turns_after_ensure

        turn = ctx.load_turn(scope.turn)
        assert turn is not None
        resolved = resolve_homeworld_services(ctx)
        baseline_result = ensure_homeworld_baseline(resolved, shell_turn=turn)
        for refine_turn_number in range(
            baseline_result.game_state.baseline_turn,
            scope.turn + 1,
        ):
            refine_turn = ctx.load_turn(refine_turn_number)
            assert refine_turn is not None
            ensure_homeworld_evidence_refined(
                resolved,
                shell_turn=refine_turn,
                game_state_baseline_turn=baseline_result.game_state.baseline_turn,
                fleet_built_turns=_fleet_built_turns_after_ensure(
                    ctx,
                    refine_turn,
                    resolved,
                ),
            )
        return True

    with (
        patch.object(
            AnalyticQueryContext,
            "dependency_walk_unavailable",
            tracking_dependency_walk_unavailable,
        ),
        patch.object(
            export_ensure_module,
            "ensure_export_scope_via_orchestrator",
            tracking_ensure_via_orchestrator,
        ),
    ):
        assert ensure_homeworld_export(ctx, ExportScope(game_id=628580, perspective=1, turn=3))

    assert walk_scopes == [(ANALYTIC_ID, 3)]
    assert orchestrator_calls == [(ANALYTIC_ID, 3)]
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
        HomeworldEvidenceAggregate(
            turn=3,
            baseline_turn=1,
            evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
        ),
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
    from api.analytics.homeworld_locator.location_evidence import (
        collect_machine_location_provenances,
    )
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence

    turn = _load_turn()
    observations = (
        OriginDistanceObservation(turn=2, x=100, y=200, matched_planet_ids=(10,)),
        OriginDistanceObservation(turn=3, x=110, y=210, matched_planet_ids=(10,)),
    )
    location_provenances = collect_machine_location_provenances(
        origin_distance_observations=observations,
    )
    derived = derive_candidates_from_merged_evidence(
        (_candidate(10),),
        MergedHomeworldEvidence(
            location_provenances=location_provenances,
            sector_owner_sets=(),
            planet_owner_sets=(),
        ),
        race_id_by_owner_slot={},
    )
    assert derived[0].confidence_tier == CONFIDENCE_POSSIBLE
    # OD-only lists do not feed definite-keyed culls as a promote path either.
    candidates = apply_definite_keyed_candidate_culls(
        derived,
        planets=turn.planets,
        settings_turn=turn,
        player_count=11,
    )
    assert candidates[0].confidence_tier == CONFIDENCE_POSSIBLE


def test_single_starbase_promotion_materializes_without_owner_assignment() -> None:
    from api.analytics.homeworld_locator.location_evidence import (
        collect_machine_location_provenances,
    )
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence

    turn = _load_turn()
    orphan = _candidate(10, perspective=None)
    promotions = (HomeworldSingleStarbasePromotion(planet_id=10, turn=5),)
    location_provenances = collect_machine_location_provenances(
        single_starbase_promotions=promotions,
    )
    derived = derive_candidates_from_merged_evidence(
        (orphan,),
        MergedHomeworldEvidence(
            location_provenances=location_provenances,
            sector_owner_sets=(),
            planet_owner_sets=(),
        ),
        race_id_by_owner_slot={},
    )
    candidates = apply_definite_keyed_candidate_culls(
        derived,
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


def test_neighborhood_cull_preserves_durable_assert_location_shell(template_planet) -> None:
    """Assert shells without asserted_cue survive neighborhood cull via durable keys."""
    from api.analytics.homeworld_locator.models import PROVENANCE_ASSERTED, LocationProvenance
    from api.analytics.homeworld_locator.types import ensure_candidates_for_asserted_locations

    definite = _planet(template_planet, planet_id=1, x=0, y=0)
    assert_shell = _planet(template_planet, planet_id=2, x=100, y=0)
    planets_by_id = {1: definite, 2: assert_shell}
    asserted = (LocationProvenance(kind=PROVENANCE_ASSERTED, turn=3, planet_id=2),)
    seeded = ensure_candidates_for_asserted_locations(
        inferred=(
            HomeworldCandidateRecord(
                planet_id=1, perspective=1, confidence_tier=CONFIDENCE_DEFINITE
            ),
        ),
        asserted_location_provenances=asserted,
    )
    assert next(row for row in seeded if row.planet_id == 2).asserted_cue is False

    without_keys = cull_definite_neighborhood_candidates(
        seeded,
        planets_by_id,
        min_separation_ly=430.0,
    )
    assert [row.planet_id for row in without_keys] == [1]

    with_keys = cull_definite_neighborhood_candidates(
        seeded,
        planets_by_id,
        min_separation_ly=430.0,
        protected_planet_ids=frozenset(row.planet_id for row in asserted),
    )
    assert [row.planet_id for row in with_keys] == [1, 2]


def test_culls_after_strength_resolve_drop_demoted_machine_near_assert(
    template_planet, sample_settings
) -> None:
    """Assert demotes nearby machine definite; post-derive culls must drop the machine pin.

    Pre-resolution culls keep both (machine definite + protected assert shell). After
    derive the machine is only possible beside an asserted definite -- illegal unless
    co-sector / neighborhood culls run on strength-resolved tiers.
    """
    from api.analytics.homeworld_locator.layout_distributions_asset import (
        CategoryLayoutDistributions,
        LayoutDistributionsAsset,
        SmoothedMetricDistribution,
    )
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence
    from api.analytics.homeworld_locator.models import (
        PROVENANCE_ASSERTED,
        PROVENANCE_BASELINE_PROFILE,
        LocationProvenance,
    )
    from api.analytics.homeworld_locator.types import ensure_candidates_for_asserted_locations
    from api.concepts.homeworld_layout import HW_DISTRIBUTION_CIRCULAR, MAP_SHAPE_ROUND

    machine = _planet(template_planet, planet_id=1, x=500, y=0)
    asserted_planet = _planet(template_planet, planet_id=2, x=550, y=20)
    planets = [machine, asserted_planet]
    asserted = (LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=2),)
    protected = frozenset({2})
    seeded = ensure_candidates_for_asserted_locations(
        inferred=(
            HomeworldCandidateRecord(
                planet_id=1, perspective=1, confidence_tier=CONFIDENCE_DEFINITE
            ),
        ),
        asserted_location_provenances=asserted,
    )
    turn = replace(
        _load_turn(),
        planets=planets,
        settings=replace(
            sample_settings,
            hwdistribution=HW_DISTRIBUTION_CIRCULAR,
            mapshape=MAP_SHAPE_ROUND,
            turn=5,
        ),
    )
    neighbor = SmoothedMetricDistribution(
        sample_count=10,
        support_min=430.0,
        support_max=600.0,
        mean=500.0,
        std=30.0,
    )
    layout_asset = LayoutDistributionsAsset(
        schema_version=2,
        bin_width_ly=10.0,
        cost_model="normal_neg_log_density",
        categories={
            "epic": CategoryLayoutDistributions(
                center_distance=neighbor, neighbor_separation=neighbor
            ),
            "standard": CategoryLayoutDistributions(
                center_distance=neighbor, neighbor_separation=neighbor
            ),
        },
        source={},
    )

    pre_resolve = apply_definite_keyed_candidate_culls(
        seeded,
        planets=planets,
        settings_turn=turn,
        player_count=11,
        layout_asset=layout_asset,
        protected_planet_ids=protected,
    )
    assert {row.planet_id for row in pre_resolve} == {1, 2}

    derived = derive_candidates_from_merged_evidence(
        pre_resolve,
        MergedHomeworldEvidence(
            location_provenances=(
                LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=1),
                LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=2),
            ),
            sector_owner_sets=(),
            planet_owner_sets=(),
        ),
        race_id_by_owner_slot={},
    )
    by_planet = {row.planet_id: row for row in derived}
    assert by_planet[2].confidence_tier == CONFIDENCE_DEFINITE
    assert by_planet[1].confidence_tier == CONFIDENCE_POSSIBLE

    post_resolve = apply_definite_keyed_candidate_culls(
        derived,
        planets=planets,
        settings_turn=turn,
        player_count=11,
        layout_asset=layout_asset,
        protected_planet_ids=protected,
    )
    assert [row.planet_id for row in post_resolve] == [2]
    assert post_resolve[0].confidence_tier == CONFIDENCE_DEFINITE
    assert post_resolve[0].asserted_cue is True


def test_materialize_homeworld_candidates_culls_after_assert_wins(
    template_planet, sample_settings, persistence, monkeypatch
) -> None:
    """Full shell materialize must not leave demoted machine pins near asserted definites."""
    from api.analytics.homeworld_locator.baseline_ensure import materialize_homeworld_candidates
    from api.analytics.homeworld_locator.models import (
        PROVENANCE_ASSERTED,
        PROVENANCE_BASELINE_PROFILE,
        LocationProvenance,
    )
    from api.concepts.homeworld_layout import HW_DISTRIBUTION_CIRCULAR, MAP_SHAPE_ROUND

    machine = _planet(template_planet, planet_id=1, x=500, y=0)
    asserted_planet = _planet(template_planet, planet_id=2, x=550, y=20)
    planets = [machine, asserted_planet]
    shell_turn = replace(
        _load_turn(),
        planets=planets,
        settings=replace(
            sample_settings,
            hwdistribution=HW_DISTRIBUTION_CIRCULAR,
            mapshape=MAP_SHAPE_ROUND,
            turn=5,
        ),
    )
    game_state = HomeworldLocatorGameState(
        candidates=(
            HomeworldCandidateRecord(
                planet_id=1, perspective=1, confidence_tier=CONFIDENCE_DEFINITE
            ),
        ),
        baseline_turn=1,
        baseline_degraded=False,
        asserted_location_provenances=(
            LocationProvenance(kind=PROVENANCE_ASSERTED, turn=5, planet_id=2),
        ),
    )
    aggregate = HomeworldEvidenceAggregate(
        turn=5,
        baseline_turn=1,
        location_provenances=(
            LocationProvenance(kind=PROVENANCE_BASELINE_PROFILE, turn=1, planet_id=1),
        ),
        evidence_algorithm_version=HOMEWORLD_EVIDENCE_ALGORITHM_VERSION,
    )
    monkeypatch.setattr(
        "api.analytics.homeworld_locator.baseline_ensure.apply_layout_prior_most_probable",
        lambda candidates, **_kwargs: tuple(candidates),
    )
    monkeypatch.setattr(
        "api.analytics.homeworld_locator.baseline_ensure._previous_turn_most_probable_planet_ids",
        lambda *_args, **_kwargs: frozenset(),
    )
    # Sample turn roster is not 11 players; force neighborhood support so the
    # assert-vs-nearby-machine failure mode is observable without roster padding.
    monkeypatch.setattr(
        "api.analytics.homeworld_locator.evidence_refine.neighbor_separation_support_min",
        lambda *_args, **_kwargs: 430.0,
    )
    services = _services(persistence, {5: shell_turn})
    materialized = materialize_homeworld_candidates(
        services,
        candidates=game_state.candidates,
        aggregate=aggregate,
        game_state=game_state,
        shell_turn=shell_turn,
        baseline_turn=1,
        baseline_degraded=False,
    )
    assert [row.planet_id for row in materialized] == [2]
    assert materialized[0].confidence_tier == CONFIDENCE_DEFINITE
    assert materialized[0].asserted_cue is True


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
    candidates = apply_definite_keyed_candidate_culls(
        (
            HomeworldCandidateRecord(
                planet_id=1, perspective=1, confidence_tier=CONFIDENCE_DEFINITE
            ),
            HomeworldCandidateRecord(
                planet_id=2, perspective=None, confidence_tier=CONFIDENCE_POSSIBLE
            ),
        ),
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


def test_stale_evidence_algorithm_version_forces_floor_rerefine(persistence) -> None:
    """Version 0 floor at baseline shell must recompute, stamp, and persist."""
    from api.analytics.homeworld_locator.evidence_ensure import (
        ensure_homeworld_evidence_refined,
        evidence_refined_through_shell,
    )

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turns = {1: turn_one}
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1, evidence_algorithm_version=0),
    )
    assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=1) is False
    aggregate = ensure_homeworld_evidence_refined(
        services,
        shell_turn=turn_one,
        game_state_baseline_turn=1,
    )
    assert aggregate.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
    stored = persistence.get_evidence_aggregate(628580, 1, 1)
    assert stored is not None
    assert stored.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
    assert evidence_refined_through_shell(services, baseline_turn=1, shell_turn=1) is True


def test_stale_floor_without_ensure_floor_rewrite_raises(persistence) -> None:
    """Floor algo bumps are owned by ensure_evidence_floor_algorithm_current only."""
    from api.analytics.homeworld_locator.evidence_ensure import (
        compute_homeworld_evidence_refine_step_detailed,
    )
    from api.errors import ValidationError

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turns = {1: turn_one}
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1, evidence_algorithm_version=0),
    )
    with pytest.raises(ValidationError, match="ensure_evidence_floor_algorithm_current"):
        compute_homeworld_evidence_refine_step_detailed(services, turn=turn_one)


def test_floor_algorithm_rewrite_clears_sticky_ownership(persistence) -> None:
    """Algo bump must reset ownership sets before re-accumulate (loosening-safe)."""
    from api.analytics.homeworld_locator.evidence_ensure import (
        ensure_evidence_floor_algorithm_current,
    )
    from api.analytics.homeworld_locator.models import (
        PROVENANCE_SHIP_TRAVEL_ENVELOPE,
        OwnershipProvenance,
        SectorOwnerMember,
    )

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turns = {1: turn_one}
    services = _services(persistence, turns)
    stale_member = SectorOwnerMember(
        owner_slot=2,
        provenances=(
            OwnershipProvenance(
                kind=PROVENANCE_SHIP_TRAVEL_ENVELOPE,
                turn=1,
                ship_id=99,
                radius_ly=10.0,
                age_source="fleet_built_turn",
            ),
        ),
    )
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        HomeworldEvidenceAggregate(
            turn=1,
            baseline_turn=1,
            evidence_algorithm_version=0,
            sector_owner_sets=((0, (stale_member,)),),
            owner_possible_sectors=((2, (0,)),),
        ),
    )
    assert (
        ensure_evidence_floor_algorithm_current(
            services,
            baseline_turn=1,
            fleet_built_turns={},
        )
        is True
    )
    stored = persistence.get_evidence_aggregate(628580, 1, 1)
    assert stored is not None
    assert stored.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
    # Stale sticky rows must not survive as the sole rewritten state when the
    # baseline turn has no ships to re-pin (empty ownership after clear+re-accumulate).
    assert stored.sector_owner_sets == ()
    assert stored.owner_possible_sectors == ()


def test_floor_algorithm_rewrite_backfills_baseline_profile_before_od_demotion(
    persistence,
) -> None:
    """Stale empty-profile floor + OD mint must not demote game-global baseline pins."""
    from api.analytics.homeworld_locator.evidence_ensure import (
        ensure_evidence_floor_algorithm_current,
    )
    from api.analytics.homeworld_locator.materialize_from_provenances import (
        derive_candidates_from_merged_evidence,
    )
    from api.analytics.homeworld_locator.merge_above_read import MergedHomeworldEvidence
    from api.analytics.homeworld_locator.models import (
        PROVENANCE_BASELINE_PROFILE,
        PROVENANCE_ORIGIN_DISTANCE,
        LocationProvenance,
    )

    turn_one = replace(_load_turn(), settings=replace(_load_turn().settings, turn=1))
    turns = {1: turn_one}
    services = _services(persistence, turns)
    definite = HomeworldCandidateRecord(
        planet_id=10,
        perspective=1,
        confidence_tier=CONFIDENCE_DEFINITE,
    )
    possible = HomeworldCandidateRecord(
        planet_id=20,
        perspective=None,
        confidence_tier=CONFIDENCE_POSSIBLE,
    )
    # Legacy floor: algo version stale, no baseline_profile rows, but OD already
    # recorded (the production demotion path after mint without profiles).
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, definite, possible),
        HomeworldEvidenceAggregate(
            turn=1,
            baseline_turn=1,
            evidence_algorithm_version=0,
            origin_distance_observations=(
                OriginDistanceObservation(turn=1, x=1, y=2, matched_planet_ids=(20,)),
            ),
            location_provenances=(
                LocationProvenance(kind=PROVENANCE_ORIGIN_DISTANCE, turn=1, planet_id=20),
            ),
        ),
    )
    assert (
        ensure_evidence_floor_algorithm_current(
            services,
            baseline_turn=1,
            fleet_built_turns={},
        )
        is True
    )
    stored = persistence.get_evidence_aggregate(628580, 1, 1)
    assert stored is not None
    assert stored.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION
    kinds = {(row.kind, row.planet_id) for row in stored.location_provenances}
    assert (PROVENANCE_BASELINE_PROFILE, 10) in kinds
    assert (PROVENANCE_ORIGIN_DISTANCE, 20) in kinds

    derived = derive_candidates_from_merged_evidence(
        (definite, possible),
        MergedHomeworldEvidence(
            location_provenances=stored.location_provenances,
            sector_owner_sets=(),
            planet_owner_sets=(),
        ),
        race_id_by_owner_slot={},
    )
    by_planet = {row.planet_id: row for row in derived}
    assert by_planet[10].confidence_tier == CONFIDENCE_DEFINITE
    assert by_planet[20].confidence_tier == CONFIDENCE_POSSIBLE


def test_fleet_built_turns_from_final_ledgers_merges_known_ages(sample_turn) -> None:
    """Sync ensure source: final on-disk ledgers supply ship_id -> built_turn."""
    from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
    from api.analytics.fleet.types import (
        FleetAcquisitionLedger,
        FleetFieldKnown,
        FleetMaterializationProvenance,
        FleetShipRecord,
        FleetShipRecordFields,
        PersistedFleetLedger,
    )
    from api.analytics.homeworld_locator.fleet_built_turns import (
        fleet_built_turns_from_final_ledgers,
    )
    from api.analytics.turn_roster import iter_turn_players

    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=sample_turn.game.id,
        perspective=1,
        stored_turns={sample_turn.settings.turn: sample_turn},
    )
    player_ids = [player.id for player in iter_turn_players(sample_turn)]
    assert player_ids
    owner = player_ids[0]
    fleet_services.persistence.put_ledger(
        fleet_services.game_id,
        fleet_services.perspective,
        sample_turn.settings.turn,
        owner,
        PersistedFleetLedger(
            ledger=FleetAcquisitionLedger(
                player_id=owner,
                records=[
                    FleetShipRecord(
                        record_id="rec-42",
                        fields=FleetShipRecordFields(
                            ship_id=FleetFieldKnown(42),
                            built_turn=FleetFieldKnown(7),
                        ),
                    ),
                ],
            ),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )
    built = fleet_built_turns_from_final_ledgers(
        fleet_services.persistence,
        game_id=fleet_services.game_id,
        perspective=fleet_services.perspective,
        turn_number=sample_turn.settings.turn,
        player_ids=player_ids,
    )
    assert built[42] == 7


def test_stale_prior_evidence_algorithm_version_raises(persistence) -> None:
    """Advancing past a stale mid-chain prior must fail closed so DAG rewalks."""
    from api.analytics.homeworld_locator.evidence_ensure import (
        compute_homeworld_evidence_refine_step_detailed,
    )
    from api.errors import ValidationError

    turn_one = replace(
        _load_turn(),
        settings=replace(_load_turn().settings, turn=1, acceleratedturns=0),
    )
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
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(
            turn=2,
            baseline_turn=1,
            evidence_algorithm_version=0,
        ),
    )
    with pytest.raises(ValidationError, match="stale evidenceAlgorithmVersion"):
        compute_homeworld_evidence_refine_step_detailed(services, turn=turn_three)


def test_export_ensure_rewalks_stale_evidence_algorithm_chain(persistence) -> None:
    """Shell ensure must rewrite a version-0 floor then advance, not warn-banner."""
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
    }
    services = _services(persistence, turns)
    persistence.put_baseline(
        628580,
        1,
        _baseline_state(turn_one.settings, _candidate(10)),
        HomeworldEvidenceAggregate(turn=1, baseline_turn=1, evidence_algorithm_version=0),
    )
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(turn=2, baseline_turn=1, evidence_algorithm_version=0),
    )
    persistence.put_evidence_aggregate(
        628580,
        1,
        HomeworldEvidenceAggregate(turn=3, baseline_turn=1, evidence_algorithm_version=0),
    )

    ctx = make_analytic_compute_context(
        turns[3],
        load_turn=lambda n: turns.get(n),
        export_services=_export_services(services, turns),
    ).exports
    assert (
        ensure_homeworld_export(
            ctx,
            ExportScope(game_id=628580, perspective=1, turn=3),
        )
        is True
    )
    for turn_number in (1, 2, 3):
        stored = persistence.get_evidence_aggregate(628580, 1, turn_number)
        assert stored is not None
        assert stored.evidence_algorithm_version == HOMEWORLD_EVIDENCE_ALGORITHM_VERSION


@pytest.fixture
def template_planet(sample_turn) -> Planet:
    return sample_turn.planets[0]


@pytest.fixture
def sample_settings(sample_turn):
    return sample_turn.settings


@pytest.fixture
def sample_turn():
    return _load_turn()
