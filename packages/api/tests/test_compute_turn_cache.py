"""Tests for compute orchestrator turn cache and job wire prefetch."""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
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
from api.compute.turn_cache import TurnInfoCache
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


@pytest.fixture(autouse=True)
def _isolate_compute_pool_singleton():
    from api.compute.pools import shutdown_compute_worker_pool_for_tests
    from api.compute.runtime import reset_orchestrators_for_tests

    shutdown_compute_worker_pool_for_tests()
    reset_orchestrators_for_tests()
    yield
    shutdown_compute_worker_pool_for_tests()
    reset_orchestrators_for_tests()


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

    game_id = sample_turn.game.id
    perspective = sample_turn.player.id
    cache = TurnInfoCache()
    cache.get(game_id, perspective, 2, load_turn=counting_load)
    cache.get(game_id, perspective, 2, load_turn=counting_load)
    cache.get(game_id, perspective, 3, load_turn=counting_load)
    cache.get(game_id, perspective, 2, load_turn=counting_load)

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
        game_id=fleet_services.game_id,
        perspective=fleet_services.perspective,
    )
    cache = TurnInfoCache()

    def cached_load(turn_number: int):
        return cache.get(628580, 1, turn_number, load_turn=fleet_services.load_turn)

    cached_ctx = replace(ctx, load_turn=cached_load)
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
        game_id=fleet_services.game_id,
        perspective=fleet_services.perspective,
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
        game_id=stored_turns[2].game.id,
        perspective=stored_turns[2].player.id,
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
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    orchestrator.turn_cache.get(
        ctx.game_id,
        ctx.perspective,
        2,
        load_turn=counting_load,
    )
    orchestrator.turn_cache.get(
        ctx.game_id,
        ctx.perspective,
        2,
        load_turn=counting_load,
    )

    assert load_calls == [2]


def test_orchestrator_turn_cache_follows_process_cache_replace(sample_turn) -> None:
    from api.compute.orchestration_bundle import OrchestrationBundle
    from api.compute.turn_cache import (
        get_process_turn_info_cache,
        replace_process_turn_info_cache,
        worker_turn_info_cache_maxsize,
    )
    from api.compute.worker_turn_cache import init_worker_turn_cache

    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    load_calls: list[int] = []

    def counting_load(turn_number: int):
        load_calls.append(turn_number)
        return stored_turns.get(turn_number)

    ctx = make_analytic_query_context(
        stored_turns[2],
        TurnAnalyticsOptions(),
        load_turn=counting_load,
        game_id=stored_turns[2].game.id,
        perspective=stored_turns[2].player.id,
    )
    orchestrator = ComputeOrchestrator(compute_registry={})
    captured_before = orchestrator.turn_cache
    assert captured_before is get_process_turn_info_cache()

    init_worker_turn_cache()
    try:
        live = get_process_turn_info_cache()
        assert live is not captured_before
        assert orchestrator.turn_cache is live
        assert live.maxsize == worker_turn_info_cache_maxsize()

        spliced = orchestrator._ctx_for_bundle(OrchestrationBundle.from_context(ctx))
        first = spliced.load_turn(2)
        second = spliced.load_turn(2)
        assert first is second
        assert load_calls == [2]
        assert live.underlying_load_calls == 1
        assert captured_before.underlying_load_calls == 0
    finally:
        replace_process_turn_info_cache()


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
        game_id=fleet_services.game_id,
        perspective=fleet_services.perspective,
    )
    compute_registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry)
    player_id = next(row.ownerid for row in sample_turn.scores)
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
        player_id=player_id,
    )

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    del handle

    assert load_calls
    assert orchestrator.turn_cache.underlying_load_calls == len(load_calls)
    assert {1, 2}.issubset(set(load_calls))


def test_worker_turn_cache_reuses_turn_wire_deserialize(sample_turn) -> None:
    from api.compute.turn_cache import clear_process_turn_info_cache

    clear_process_turn_info_cache()
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
    from api.analytics.fleet.chain import ensure_fleet_baseline_for_player
    from api.analytics.fleet.held_solutions import FleetInferenceSupport
    from api.analytics.military_score_inference.solver import STATUS_EXACT
    from api.serialization.inference_row_persistence import PersistedInferenceRow
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService
    from api.storage.memory_asset import MemoryAssetBackend

    from tests.scores_exports_helpers import put_persisted_row

    reset_worker_deserialize_calls_for_tests()
    stored_turns = build_stored_turn_chain(sample_turn, through_turn=2)
    player_id = next(row.ownerid for row in sample_turn.scores)
    inference_persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scores_services = ScoresExportContext(persistence=inference_persistence)
    # Durable closed scores@2 lets finalization refine; observation has no scores ENSURE edge.
    put_persisted_row(
        inference_persistence,
        stored_turns[2],
        player_id,
        PersistedInferenceRow(
            status=STATUS_EXACT,
            summary="seeded for turn-cache fleet pool",
            solution_count=0,
            is_complete=True,
            solutions=[],
        ),
        host_turn=2,
        perspective_id=1,
    )
    fleet_services = build_ephemeral_fleet_compute_services(
        sample_turn,
        game_id=628580,
        perspective=1,
        stored_turns=stored_turns,
        inference=FleetInferenceSupport(scores_services=scores_services),
    )
    # Final fleet@1 satisfies the prior-turn DAG edge so only fleet@2 hits the pool
    # (turn-1 roots are no longer elided from the walk).
    fleet_services.persistence.put_ledger(
        628580,
        1,
        1,
        player_id,
        PersistedFleetLedger(
            ledger=ensure_fleet_baseline_for_player(628580, 1, stored_turns[1], player_id),
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
        ),
    )
    ctx = make_analytic_query_context(
        stored_turns[2],
        TurnAnalyticsOptions(),
        load_turn=fleet_services.load_turn,
        export_services={
            _FLEET_ANALYTIC_ID: fleet_services,
            SCORES_ANALYTIC_ID: scores_services,
        },
        game_id=fleet_services.game_id,
        perspective=fleet_services.perspective,
    )
    compute_registry = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry, worker_pool=pool)
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=2,
        player_id=player_id,
    )

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
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


def _job_wire_for_turn(turn) -> dict:
    return {
        "gameId": turn.game.id,
        "perspective": turn.player.id,
        "materializeTurn": turn.settings.turn,
        "turnWire": turn_info_to_json(turn),
    }


def _turn_load_wired_to_process_cache(storage):
    from api.compute.turn_cache import get_process_turn_info_cache
    from api.services.credential_service import CredentialService
    from api.services.game_service import GameService
    from api.services.turn_load_service import TurnLoadService

    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    return TurnLoadService(
        storage,
        credentials,
        games,
        turn_info_cache=get_process_turn_info_cache,
    )


def test_turn_load_service_process_cache_follows_replace(sample_turn) -> None:
    from unittest.mock import MagicMock

    from api.compute.turn_cache import (
        get_process_turn_info_cache,
        replace_process_turn_info_cache,
    )
    from api.compute.worker_turn_cache import init_worker_turn_cache

    storage = MagicMock()
    storage.get.return_value = turn_info_to_json(sample_turn)
    turns = _turn_load_wired_to_process_cache(storage)
    captured_before = get_process_turn_info_cache()
    init_worker_turn_cache()
    try:
        live = get_process_turn_info_cache()
        assert live is not captured_before
        turns.get_turn_info(sample_turn.game.id, sample_turn.player.id, sample_turn.settings.turn)
        assert live.underlying_load_calls == 1
        assert captured_before.underlying_load_calls == 0
    finally:
        replace_process_turn_info_cache()


def test_storage_then_turn_wire_fill_shares_cached_object(sample_turn) -> None:
    from api.compute.turn_cache import clear_process_turn_info_cache
    from api.services.turn_load_service import TurnLoadService
    from api.storage.memory_asset import MemoryAssetBackend

    clear_process_turn_info_cache()
    reset_worker_deserialize_calls_for_tests()
    turn = sample_turn
    storage = MemoryAssetBackend(initial={})
    storage.put(
        TurnLoadService.turn_store_key(turn.game.id, turn.player.id, turn.settings.turn),
        turn_info_to_json(turn),
    )
    turns = _turn_load_wired_to_process_cache(storage)

    first = turns.get_turn_info(turn.game.id, turn.player.id, turn.settings.turn)
    second = turn_from_materialization_job_wire(_job_wire_for_turn(turn))

    assert first is second
    assert worker_deserialize_calls() == 1


def test_turn_wire_then_storage_fill_does_not_reread_storage(sample_turn) -> None:
    from api.compute.turn_cache import clear_process_turn_info_cache
    from api.services.turn_load_service import TurnLoadService
    from api.storage.memory_asset import MemoryAssetBackend

    clear_process_turn_info_cache()
    reset_worker_deserialize_calls_for_tests()
    turn = sample_turn
    storage = MemoryAssetBackend(initial={})
    store_key = TurnLoadService.turn_store_key(turn.game.id, turn.player.id, turn.settings.turn)
    storage.put(store_key, turn_info_to_json(turn))
    turns = _turn_load_wired_to_process_cache(storage)

    first = turn_from_materialization_job_wire(_job_wire_for_turn(turn))
    second = turns.get_turn_info(turn.game.id, turn.player.id, turn.settings.turn)

    assert first is second
    assert worker_deserialize_calls() == 1
    storage.delete(store_key)
    third = turns.get_turn_info(turn.game.id, turn.player.id, turn.settings.turn)
    assert third is first


def test_scores_turn_load_hits_cache_on_second_get(sample_turn) -> None:
    from unittest.mock import MagicMock

    from api.compute.turn_cache import clear_process_turn_info_cache
    from api.services.turn_load_service import TurnLoadService

    clear_process_turn_info_cache()
    storage = MagicMock()
    storage.get.return_value = turn_info_to_json(sample_turn)
    turns = _turn_load_wired_to_process_cache(storage)
    game_id = sample_turn.game.id
    perspective = sample_turn.player.id
    turn_number = sample_turn.settings.turn

    first = turns.get_turn_info(game_id, perspective, turn_number)
    second = turns.get_turn_info(game_id, perspective, turn_number)

    assert first is second
    storage.get.assert_called_once_with(
        TurnLoadService.turn_store_key(game_id, perspective, turn_number)
    )


def _turn_load_with_cache(storage, cache: TurnInfoCache, *, on_turn_stored=None):
    from api.services.credential_service import CredentialService
    from api.services.game_service import GameService
    from api.services.turn_load_service import TurnLoadService

    credentials = CredentialService(storage)
    games = GameService(storage, credentials)
    return TurnLoadService(
        storage,
        credentials,
        games,
        on_turn_stored=on_turn_stored,
        turn_info_cache=cache,
    )


def test_storing_turn_document_puts_deserialized_turn(sample_turn) -> None:
    from unittest.mock import MagicMock

    from api.services.turn_load_service import TurnLoadService

    cache = TurnInfoCache()
    storage = MagicMock()
    on_turn_stored = MagicMock()
    turns = _turn_load_with_cache(storage, cache, on_turn_stored=on_turn_stored)
    game_id = sample_turn.game.id
    perspective = sample_turn.player.id
    turn_number = sample_turn.settings.turn
    rst = turn_info_to_json(sample_turn)

    turns._store_turn_rst(game_id, perspective, turn_number, rst, turn=sample_turn)
    loaded = turns.get_turn_info(game_id, perspective, turn_number)

    assert loaded is sample_turn
    assert cache.underlying_load_calls == 0
    storage.get.assert_not_called()
    storage.put.assert_called_once_with(
        TurnLoadService.turn_store_key(game_id, perspective, turn_number),
        rst,
    )
    on_turn_stored.assert_called_once_with(game_id, perspective, turn_number)


def test_storing_turn_document_replaces_stale_cached_turn(sample_turn) -> None:
    from unittest.mock import MagicMock

    cache = TurnInfoCache()
    storage = MagicMock()
    storage.get.return_value = turn_info_to_json(sample_turn)
    turns = _turn_load_with_cache(storage, cache)
    game_id = sample_turn.game.id
    perspective = sample_turn.player.id
    turn_number = sample_turn.settings.turn
    written = turn_info_from_json(turn_info_to_json(sample_turn))

    stale = turns.get_turn_info(game_id, perspective, turn_number)
    assert stale is not written
    assert cache.underlying_load_calls == 1
    assert storage.get.call_count == 1

    turns._store_turn_rst(
        game_id,
        perspective,
        turn_number,
        turn_info_to_json(written),
        turn=written,
    )
    loaded = turns.get_turn_info(game_id, perspective, turn_number)

    assert loaded is written
    assert loaded is not stale
    assert cache.underlying_load_calls == 1
    assert storage.get.call_count == 1


def test_storing_turn_document_without_turn_drops_cached_turn(sample_turn) -> None:
    from unittest.mock import MagicMock

    from api.services.turn_load_service import TurnLoadService

    cache = TurnInfoCache()
    storage = MagicMock()
    storage.get.return_value = turn_info_to_json(sample_turn)
    on_turn_stored = MagicMock()
    turns = _turn_load_with_cache(storage, cache, on_turn_stored=on_turn_stored)
    game_id = sample_turn.game.id
    perspective = sample_turn.player.id
    turn_number = sample_turn.settings.turn
    rst = turn_info_to_json(sample_turn)

    turns.get_turn_info(game_id, perspective, turn_number)
    turns.get_turn_info(game_id, perspective, turn_number)
    assert cache.underlying_load_calls == 1
    assert storage.get.call_count == 1

    turns._store_turn_rst(game_id, perspective, turn_number, rst)
    turns.get_turn_info(game_id, perspective, turn_number)

    assert cache.underlying_load_calls == 2
    assert storage.get.call_count == 2
    storage.put.assert_called_once_with(
        TurnLoadService.turn_store_key(game_id, perspective, turn_number),
        rst,
    )
    on_turn_stored.assert_called_once_with(game_id, perspective, turn_number)


def test_turn_info_cache_put_replaces_cached_turn(sample_turn) -> None:
    loads: list[int] = []
    written = turn_info_from_json(turn_info_to_json(sample_turn))

    def counting_load(turn_number: int):
        loads.append(turn_number)
        return sample_turn

    cache = TurnInfoCache()
    cache.get(628580, 1, 5, load_turn=counting_load)
    cache.put(628580, 1, 5, written)
    hit = cache.get(628580, 1, 5, load_turn=counting_load)

    assert hit is written
    assert hit is not sample_turn
    assert loads == [5]


def test_turn_info_cache_drop_forces_reload(sample_turn) -> None:
    loads: list[int] = []

    def counting_load(turn_number: int):
        loads.append(turn_number)
        return sample_turn

    cache = TurnInfoCache()
    cache.get(628580, 1, 5, load_turn=counting_load)
    cache.get(628580, 1, 5, load_turn=counting_load)
    cache.drop(628580, 1, 5)
    cache.get(628580, 1, 5, load_turn=counting_load)

    assert loads == [5, 5]


def test_worker_turn_cache_import_does_not_load_fastapi_or_dag() -> None:
    import subprocess
    import sys
    from pathlib import Path

    script = """
from api.compute.worker_turn_cache import init_worker_turn_cache
import sys
blocked = [
    name
    for name in sys.modules
    if name == "fastapi"
    or name.startswith("fastapi.")
    or name == "api.compute.dag"
    or name.startswith("api.compute.dag.")
]
if blocked:
    raise SystemExit(f"unexpected modules: {blocked}")
if init_worker_turn_cache is None:
    raise SystemExit("init_worker_turn_cache missing")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
