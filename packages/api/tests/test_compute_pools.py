"""Tests for compute worker pool priority dequeue and orchestrator integration."""

from __future__ import annotations

import threading
import time
from collections import deque

import pytest
from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_types import ExportScope
from api.analytics.exports.registry import merge_export_registry
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputePriorityBand,
    ComputeRequest,
    ComputeScope,
    ComputeStepSpec,
    ComputeWorkerPool,
    PoolWorkItem,
    ScopeKeySpec,
    build_compute_registry,
    dequeue_next_work_item,
    normalize_export_scope_to_compute_scope,
)

from tests.compute_pool_test_helpers import (
    run_interpreter_materialize,
    run_process_materialize,
)
from tests.fixtures.export_framework.fixture_catalog import make_fixture_catalog
from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_foundation import _StubPersistencePolicy

_ROW_SCOPE_KEY = ScopeKeySpec(axes=("perspective", "turn", "player_id"))
_ANALYTIC_ID = "pool-fairness"
_FLEET_ANALYTIC_ID = "pool-fleet"

_POOL_EXPORT_REGISTRY = merge_export_registry(
    make_fixture_catalog(_ANALYTIC_ID),
    make_fixture_catalog(_FLEET_ANALYTIC_ID),
)


def _catalog_entry(analytic_id: str = _ANALYTIC_ID) -> TurnAnalyticCatalogEntry:
    return TurnAnalyticCatalogEntry(
        id=analytic_id,
        name=analytic_id,
        supports_table=True,
        supports_map=False,
        type="selectable",
    )


def _scope_for_player(sample_turn, player_id: int) -> ComputeScope:
    export_scope = ExportScope(
        game_id=sample_turn.game.id,
        perspective=1,
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )
    return normalize_export_scope_to_compute_scope(
        export_scope,
        analytic_id=_ANALYTIC_ID,
        scope_key_spec=_ROW_SCOPE_KEY,
    )


def _work_item(
    *,
    scope: ComputeScope,
    priority_band: ComputePriorityBand = "background",
    step_index: int = 0,
    sequence: int = 0,
    backend: str = "thread",
) -> PoolWorkItem:
    return PoolWorkItem(
        scope=scope,
        step_kind="tier1" if step_index == 0 else "tier2",
        backend=backend,
        priority_band=priority_band,
        step_index=step_index,
        sequence=sequence,
    )


def test_dequeue_prefers_stream_attached_over_background(sample_turn):
    player_a = next(row.ownerid for row in sample_turn.scores)
    player_b = next(row.ownerid for row in sample_turn.scores if row.ownerid != player_a)
    scope_a = _scope_for_player(sample_turn, player_a)
    scope_b = _scope_for_player(sample_turn, player_b)
    queue = deque(
        [
            _work_item(scope=scope_a, priority_band="background", sequence=1),
            _work_item(scope=scope_b, priority_band="stream_attached", sequence=2),
        ]
    )

    item = dequeue_next_work_item(queue)

    assert item is not None
    assert item.scope == scope_b
    assert item.priority_band == "stream_attached"


def test_dequeue_prefers_interactive_ensure_over_background(sample_turn):
    player_a = next(row.ownerid for row in sample_turn.scores)
    player_b = next(row.ownerid for row in sample_turn.scores if row.ownerid != player_a)
    scope_a = _scope_for_player(sample_turn, player_a)
    scope_b = _scope_for_player(sample_turn, player_b)
    queue = deque(
        [
            _work_item(scope=scope_a, priority_band="background", sequence=1),
            _work_item(scope=scope_b, priority_band="interactive_ensure", sequence=2),
        ]
    )

    item = dequeue_next_work_item(queue)

    assert item is not None
    assert item.scope == scope_b


def test_dequeue_prefers_stream_attached_over_interactive_ensure(sample_turn):
    player_a = next(row.ownerid for row in sample_turn.scores)
    player_b = next(row.ownerid for row in sample_turn.scores if row.ownerid != player_a)
    scope_a = _scope_for_player(sample_turn, player_a)
    scope_b = _scope_for_player(sample_turn, player_b)
    queue = deque(
        [
            _work_item(scope=scope_a, priority_band="interactive_ensure", sequence=1),
            _work_item(scope=scope_b, priority_band="stream_attached", sequence=2),
        ]
    )

    item = dequeue_next_work_item(queue)

    assert item is not None
    assert item.scope == scope_b
    assert item.priority_band == "stream_attached"


def test_dequeue_tier_one_before_continuations_from_other_scopes(sample_turn):
    """Port of inference scheduler fairness: tier-1 before continuation steps."""
    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    assert len(player_ids) >= 2
    scope_a = _scope_for_player(sample_turn, player_ids[0])
    scope_b = _scope_for_player(sample_turn, player_ids[1])
    queue = deque(
        [
            _work_item(scope=scope_a, step_index=0, sequence=1),
            _work_item(scope=scope_a, step_index=1, sequence=2),
            _work_item(scope=scope_b, step_index=0, sequence=3),
        ]
    )

    first = dequeue_next_work_item(queue)
    second = dequeue_next_work_item(queue)
    third = dequeue_next_work_item(queue)

    assert first is not None and first.scope == scope_a and first.step_index == 0
    assert second is not None and second.scope == scope_b and second.step_index == 0
    assert third is not None and third.scope == scope_a and third.step_index == 1


def test_dequeue_continuation_round_robin_across_scopes(sample_turn):
    """Continuations dequeue in FIFO order when no tier-1 work remains."""
    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    scope_a = _scope_for_player(sample_turn, player_ids[0])
    scope_b = _scope_for_player(sample_turn, player_ids[1])
    queue = deque(
        [
            _work_item(scope=scope_a, step_index=1, sequence=1),
            _work_item(scope=scope_b, step_index=1, sequence=2),
            _work_item(scope=scope_a, step_index=2, sequence=3),
            _work_item(scope=scope_b, step_index=2, sequence=4),
        ]
    )

    order = [dequeue_next_work_item(queue) for _ in range(4)]

    assert [item.step_index for item in order if item is not None] == [1, 1, 2, 2]
    assert [item.scope for item in order if item is not None] == [
        scope_a,
        scope_b,
        scope_a,
        scope_b,
    ]


def _multi_step_thread_registration(
    execution_order: list[tuple[int, int]],
    gate: threading.Event,
) -> TurnAnalyticRegistration:
    def run_tier1(job):
        player_id = job["player_id"]
        execution_order.append((player_id, 0))
        gate.wait(timeout=1.0)
        return {"result": "tier1", "player_id": player_id}

    def run_tier2(job):
        player_id = job["player_id"]
        execution_order.append((player_id, 1))
        gate.wait(timeout=1.0)
        return {"result": "tier2", "player_id": player_id}

    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(),
        compute=lambda _ctx: {"analyticId": _ANALYTIC_ID},
        export_catalog=make_fixture_catalog(_ANALYTIC_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(
                ComputeStepSpec(step_kind="tier1", backend="thread"),
                ComputeStepSpec(step_kind="tier2", backend="thread"),
            ),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            (
                "tier1",
                lambda scope, **_kwargs: {
                    "player_id": scope.player_id,
                    "scope": scope.analytic_id,
                },
            ),
            (
                "tier2",
                lambda scope, **_kwargs: {
                    "player_id": scope.player_id,
                    "scope": scope.analytic_id,
                },
            ),
        ),
        run_steps=(
            ("tier1", run_tier1),
            ("tier2", run_tier2),
        ),
    )


def test_pool_tier_one_jobs_run_before_continuations_from_other_scopes(sample_turn):
    """Integration: worker pool applies tier-1-before-continuation fairness."""
    execution_order: list[tuple[int, int]] = []
    gate = threading.Event()
    gate.set()
    compute_registry = build_compute_registry(
        (_multi_step_thread_registration(execution_order, gate),)
    )
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry, worker_pool=pool)

    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    scope_a = _scope_for_player(sample_turn, player_ids[0])
    scope_b = _scope_for_player(sample_turn, player_ids[1])

    orchestrator.submit(
        ComputeRequest(scope=scope_a, priority_band="stream_attached"),
    )
    gate.clear()
    time.sleep(0.05)
    orchestrator.submit(
        ComputeRequest(scope=scope_b, priority_band="stream_attached"),
    )
    gate.set()

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if len(execution_order) >= 3:
            break
        time.sleep(0.01)

    pool.shutdown()
    assert execution_order[:3] == [
        (player_ids[0], 0),
        (player_ids[1], 0),
        (player_ids[0], 1),
    ]


def test_pool_continuation_jobs_round_robin_across_scopes(sample_turn):
    execution_order: list[tuple[int, int]] = []
    gate = threading.Event()
    gate.set()
    compute_registry = build_compute_registry(
        (_multi_step_thread_registration(execution_order, gate),)
    )
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry, worker_pool=pool)

    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    scope_a = _scope_for_player(sample_turn, player_ids[0])
    scope_b = _scope_for_player(sample_turn, player_ids[1])

    orchestrator.submit(ComputeRequest(scope=scope_a, priority_band="stream_attached"))
    orchestrator.submit(ComputeRequest(scope=scope_b, priority_band="stream_attached"))
    gate.set()

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if len(execution_order) >= 4:
            break
        time.sleep(0.01)

    pool.shutdown()
    assert execution_order[:4] == [
        (player_ids[0], 0),
        (player_ids[1], 0),
        (player_ids[0], 1),
        (player_ids[1], 1),
    ]


def _interpreter_backend_registration() -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(_FLEET_ANALYTIC_ID),
        compute=lambda _ctx: {"analyticId": _FLEET_ANALYTIC_ID},
        export_catalog=make_fixture_catalog(_FLEET_ANALYTIC_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="interpreter"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", run_interpreter_materialize),),
    )


def test_pool_dispatches_interpreter_backend(sample_turn):
    compute_registry = build_compute_registry((_interpreter_backend_registration(),))
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry, worker_pool=pool)
    scope = _scope_for_player(sample_turn, next(row.ownerid for row in sample_turn.scores))
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=scope.player_id,
    )

    handle = orchestrator.submit(ComputeRequest(scope=scope))

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if handle.state == "complete":
            break
        time.sleep(0.01)

    pool.shutdown()
    assert handle.state == "complete", handle.error
    assert handle.result_wire == {"result": _FLEET_ANALYTIC_ID}
    assert pool.metrics.interpreter_executions == 1


def _process_backend_registration() -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(_FLEET_ANALYTIC_ID),
        compute=lambda _ctx: {"analyticId": _FLEET_ANALYTIC_ID},
        export_catalog=make_fixture_catalog(_FLEET_ANALYTIC_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="process"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", run_process_materialize),),
    )


def test_pool_dispatches_process_backend(sample_turn):
    compute_registry = build_compute_registry((_process_backend_registration(),))
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry, worker_pool=pool)
    scope = _scope_for_player(sample_turn, next(row.ownerid for row in sample_turn.scores))
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=scope.player_id,
    )

    handle = orchestrator.submit(ComputeRequest(scope=scope))

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if handle.state == "complete":
            break
        time.sleep(0.01)

    pool.shutdown()
    assert handle.state == "complete", handle.error
    assert handle.result_wire == {"result": _FLEET_ANALYTIC_ID}
    assert pool.metrics.process_executions == 1


def test_configured_worker_count_reads_environment(monkeypatch: pytest.MonkeyPatch):
    from api.compute.pools import configured_worker_count

    monkeypatch.setenv("COMPUTE_ORCHESTRATOR_WORKERS", "7")
    assert configured_worker_count() == 7


def _single_step_thread_registration() -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(),
        compute=lambda _ctx: {"analyticId": _ANALYTIC_ID},
        export_catalog=make_fixture_catalog(_ANALYTIC_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="thread"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"player_id": scope.player_id}),
        ),
        run_steps=(("materialize", lambda job: {"result": job["player_id"]}),),
    )


def test_concurrent_submit_with_multiple_pool_workers(sample_turn):
    """Submit from several threads while pool workers complete steps concurrently."""
    compute_registry = build_compute_registry((_single_step_thread_registration(),))
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    pool = ComputeWorkerPool(worker_count=2)
    orchestrator = ComputeOrchestrator(ctx, compute_registry=compute_registry, worker_pool=pool)

    player_ids = [row.ownerid for row in sample_turn.scores[:4]]
    scopes = [_scope_for_player(sample_turn, player_id) for player_id in player_ids]
    errors: list[BaseException] = []
    lock = threading.Lock()

    def submit_scope(scope: ComputeScope) -> None:
        try:
            handle = orchestrator.submit(ComputeRequest(scope=scope))
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if handle.state in {"complete", "failed"}:
                    break
                time.sleep(0.01)
            if handle.state != "complete":
                with lock:
                    if handle.error is not None:
                        errors.append(handle.error)
                    else:
                        errors.append(RuntimeError(f"scope {scope.player_id} did not complete"))
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=submit_scope, args=(scope,)) for scope in scopes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    pool.shutdown()
    assert errors == []
    for scope in scopes:
        assert orchestrator.nodes[scope].state == "complete"
        assert orchestrator.nodes[scope].result_wire == {"result": scope.player_id}
