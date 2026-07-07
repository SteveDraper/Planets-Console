"""Tests for compute orchestrator turn cache and job wire prefetch."""

from __future__ import annotations

import time
from dataclasses import replace

from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_context import make_analytic_query_context
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.fleet.compute_orchestration import build_fleet_materialization_leg_job_wire
from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services
from api.analytics.fleet.registration import REGISTRATION as FLEET_REGISTRATION
from api.analytics.fleet.serialization import (
    persisted_fleet_ledger_from_json,
    persisted_fleet_ledger_to_json,
)
from api.analytics.fleet.types import FleetMaterializationProvenance, PersistedFleetLedger
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeStepSpec,
    ComputeWorkerPool,
    DependencyOutputs,
    ScopeKeySpec,
    build_compute_registry,
)
from api.compute.turn_cache import OrchestratorTurnCache
from api.compute.worker_turn_cache import (
    reset_worker_deserialize_calls_for_tests,
    turn_from_materialization_job_wire,
    worker_deserialize_calls,
)
from api.serialization.turn import turn_info_from_json, turn_info_to_json

from tests.fixtures.export_framework.harness import build_stored_turn_chain
from tests.test_compute_foundation import _StubPersistencePolicy

_ROW_SCOPE_KEY = ScopeKeySpec(axes=("perspective", "turn", "player_id"))
_FLEET_ANALYTIC_ID = "fleet"


def _catalog_entry(analytic_id: str) -> TurnAnalyticCatalogEntry:
    return TurnAnalyticCatalogEntry(
        id=analytic_id,
        name=analytic_id,
        supports_table=True,
        supports_map=False,
        type="selectable",
    )


def test_orchestrator_turn_cache_avoids_duplicate_underlying_loads(sample_turn) -> None:
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=3)
    load_calls: list[int] = []

    def counting_load(turn_number: int):
        load_calls.append(turn_number)
        turn = stored_turns.get(turn_number)
        if turn is None:
            return None
        return turn_info_from_json(turn_info_to_json(turn))

    cache = OrchestratorTurnCache(counting_load)
    cache.get(2)
    cache.get(2)
    cache.get(3)
    cache.get(2)

    assert load_calls == [2, 3]


def test_fleet_job_wire_includes_prefetched_turn_wire(sample_turn) -> None:
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
        stored_turns=stored_turns,
    )
    ctx = make_analytic_query_context(
        stored_turns[2],
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )
    cache = OrchestratorTurnCache(ctx.load_turn)
    cached_ctx = replace(ctx, load_turn=cache.get)
    player_id = next(row.ownerid for row in sample_turn.scores)
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
        player_id=player_id,
    )

    job_wire = build_fleet_materialization_leg_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=cached_ctx,
    )

    assert "turnWire" in job_wire
    assert job_wire["materializeTurn"] == 2
    assert turn_info_from_json(job_wire["turnWire"]).settings.turn == 2


def test_fleet_job_wire_prefetches_prior_ledger_from_persistence(sample_turn) -> None:
    from api.analytics.fleet.chain import ensure_fleet_baseline_for_player

    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
        stored_turns=stored_turns,
    )
    ctx = make_analytic_query_context(
        stored_turns[2],
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )
    player_id = next(row.ownerid for row in sample_turn.scores)
    prior_persisted = PersistedFleetLedger(
        ledger=ensure_fleet_baseline_for_player(628580, 1, stored_turns[1], player_id),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
    )
    fleet_services.persistence.put_ledger(
        628580,
        1,
        1,
        player_id,
        prior_persisted,
    )
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
        player_id=player_id,
    )

    job_wire = build_fleet_materialization_leg_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
    )

    assert job_wire["priorLedgerWire"] is not None
    loaded_prior = persisted_fleet_ledger_from_json(job_wire["priorLedgerWire"])
    assert loaded_prior.ledger.player_id == player_id
    expected_prior = fleet_services.persistence.get_ledger(628580, 1, 1, player_id)
    assert expected_prior is not None
    assert persisted_fleet_ledger_to_json(loaded_prior) == persisted_fleet_ledger_to_json(
        expected_prior
    )
    assert (
        job_wire["baselineLedgerWire"] == persisted_fleet_ledger_to_json(expected_prior)["ledger"]
    )


def test_orchestrator_exposes_cached_load_turn(sample_turn) -> None:
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    load_calls: list[int] = []

    def counting_load(turn_number: int):
        load_calls.append(turn_number)
        return stored_turns.get(turn_number)

    ctx = make_analytic_query_context(
        stored_turns[2],
        TurnAnalyticsOptions(),
        load_turn=counting_load,
    )
    compute_registry = build_compute_registry(
        (
            TurnAnalyticRegistration(
                catalog_entry=_catalog_entry("cache-probe"),
                compute=lambda _ctx: {"analyticId": "cache-probe"},
                export_catalog=empty_export_catalog_for("cache-probe"),
                scope_key_spec=_ROW_SCOPE_KEY,
                compute_profile=AnalyticComputeProfile(
                    steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
                ),
                persistence_policy=_StubPersistencePolicy(),
                build_step_job_wires=(("materialize", lambda *_a, **_k: {}),),
                run_steps=(("materialize", lambda job: job),),
            ),
        )
    )
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)
    orchestrator.turn_cache.get(2)
    orchestrator.turn_cache.get(2)

    assert load_calls == [2]


def test_orchestrator_dag_plan_and_wire_build_share_turn_cache(sample_turn) -> None:
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
        stored_turns=stored_turns,
    )
    load_calls: list[int] = []

    def counting_load(turn_number: int):
        load_calls.append(turn_number)
        return fleet_services.load_turn(turn_number)

    ctx = make_analytic_query_context(
        stored_turns[2],
        TurnAnalyticsOptions(),
        load_turn=counting_load,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )
    compute_registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry)
    player_id = next(row.ownerid for row in sample_turn.scores)
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
        player_id=player_id,
    )

    handle = orchestrator.submit(ComputeRequest(scope=scope))
    del handle

    assert all(load_calls.count(turn) == 1 for turn in set(load_calls))
    assert {1, 2}.issubset(set(load_calls))


def test_worker_turn_cache_reuses_turn_wire_deserialize(sample_turn) -> None:
    reset_worker_deserialize_calls_for_tests()
    turn = sample_turn
    job_wire = {
        "gameId": turn.game.id,
        "perspective": turn.player.id,
        "materializeTurn": turn.settings.turn,
        "turnWire": turn_info_to_json(turn),
    }

    first = turn_from_materialization_job_wire(job_wire)
    second = turn_from_materialization_job_wire(job_wire)

    assert first.settings.turn == second.settings.turn
    assert worker_deserialize_calls() == 1


def test_pool_fleet_leg_deserializes_turn_wire_once_in_worker(sample_turn) -> None:
    reset_worker_deserialize_calls_for_tests()
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
        stored_turns=stored_turns,
    )
    ctx = make_analytic_query_context(
        stored_turns[2],
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: ScoresExportContext(),
        },
    )
    compute_registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry, worker_pool=pool)
    player_id = next(row.ownerid for row in sample_turn.scores)
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
        player_id=player_id,
    )

    handle = orchestrator.submit(ComputeRequest(scope=scope))
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if handle.state == "complete":
            break
        time.sleep(0.01)

    assert handle.state == "complete", handle.error
    assert isinstance(handle.result_wire, dict)
    assert "persistedLedgerWire" in handle.result_wire
    assert pool.metrics.interpreter_executions == 1
    assert pool.worker_deserialize_calls_for_tests() == 1

    pool.shutdown()
