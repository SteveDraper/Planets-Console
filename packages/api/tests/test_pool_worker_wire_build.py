"""Where a pool step's job wire is built: on the pool worker, never at hand-off.

The hand-off turns the dispatch snapshot into pool work and enqueues it. Every
backend's wire is built later, on the worker that picks the item, from that
one snapshot. The worker-side drop and re-check are covered in
``test_orchestrator_execution_liveness``.
"""

from __future__ import annotations

import threading
import time

import pytest
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeStepSpec,
    ComputeWorkerPool,
    PoolStepWork,
    build_compute_registry,
)
from api.compute.backend_runtime import effective_pool_backend
from api.compute.wire import StepResult
from api.config import ApiConfig, set_config

from tests.compute_orchestrator_fixtures import StubPersistencePolicy
from tests.fixtures.export_framework.fixture_catalog import make_fixture_catalog
from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_pools import (
    _FLEET_ANALYTIC_ID,
    _POOL_EXPORT_REGISTRY,
    _ROW_SCOPE_KEY,
    _catalog_entry,
    _scope_for_player,
)


def _set_interpreter_remap(monkeypatch, *, is_remapped: bool) -> None:
    set_config(
        ApiConfig(storage_backend="ephemeral", remap_interpreter_backend_to_thread=is_remapped)
    )
    monkeypatch.setattr("api.compute.backend_runtime.process_is_frozen", lambda: False)


def _interpreter_wire_registration(build_wire):
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(_FLEET_ANALYTIC_ID),
        compute=lambda _ctx: {"analyticId": _FLEET_ANALYTIC_ID},
        export_catalog=make_fixture_catalog(_FLEET_ANALYTIC_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="interpreter"),),
        ),
        persistence_policy=StubPersistencePolicy(),
        build_step_job_wires=(("materialize", build_wire),),
        run_steps=(
            (
                "materialize",
                lambda job: StepResult(outcome="complete", payload=job),
            ),
        ),
    )


def _submit_interpreter_step(sample_turn, *, pool_submitter, build_wire):
    compute_registry = build_compute_registry((_interpreter_wire_registration(build_wire),))
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        pool_submitter=pool_submitter,
    )
    scope = _scope_for_player(sample_turn, next(row.ownerid for row in sample_turn.scores))
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=scope.player_id,
    )
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    return orchestrator


@pytest.mark.parametrize(
    ("is_remapped", "expected_backend"),
    [(False, "interpreter"), (True, "thread")],
)
def test_hand_off_builds_no_wire_and_carries_the_dispatch_snapshot_to_the_pool(
    sample_turn, monkeypatch, is_remapped, expected_backend
):
    _set_interpreter_remap(monkeypatch, is_remapped=is_remapped)
    built: list[dict] = []
    submitted: list[tuple[ComputeScope, PoolStepWork]] = []

    def build_wire(scope, **kwargs):
        del scope
        built.append(kwargs)
        return {"built": True}

    def pool_submitter(node, step, *, work):
        del step
        submitted.append((node.scope, work))

    _submit_interpreter_step(sample_turn, pool_submitter=pool_submitter, build_wire=build_wire)

    assert built == []
    ((scope, work),) = submitted
    assert work.backend == expected_backend
    assert work.job_wire_for(scope) == {"built": True}
    assert built == [work.job_wire_kwargs]


@pytest.mark.parametrize(
    ("declared", "is_remapped", "expected"),
    [
        ("thread", False, "thread"),
        ("process", False, "process"),
        ("interpreter", False, "interpreter"),
        ("interpreter", True, "thread"),
        ("process", True, "process"),
    ],
)
def test_effective_pool_backend_applies_the_interpreter_remap(
    monkeypatch, declared, is_remapped, expected
):
    _set_interpreter_remap(monkeypatch, is_remapped=is_remapped)

    assert effective_pool_backend(declared) == expected


def test_effective_pool_backend_refuses_an_inline_step():
    with pytest.raises(RuntimeError, match="inline step"):
        effective_pool_backend("inline")


def test_remapped_interpreter_step_builds_its_wire_on_the_worker_from_the_dispatch_snapshot(
    sample_turn, monkeypatch
):
    _set_interpreter_remap(monkeypatch, is_remapped=True)
    built: list[dict] = []
    snapshots: list[dict] = []

    def build_wire(scope, **kwargs):
        del scope
        built.append(kwargs)
        assert threading.current_thread() in pool._workers  # noqa: SLF001
        return {"built": True}

    compute_registry = build_compute_registry((_interpreter_wire_registration(build_wire),))
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(compute_registry=compute_registry, worker_pool=pool)
    take_snapshot = orchestrator._snapshot_job_wire_kwargs  # noqa: SLF001

    def record_snapshot(node):
        snapshots.append(take_snapshot(node))
        return snapshots[-1]

    monkeypatch.setattr(orchestrator, "_snapshot_job_wire_kwargs", record_snapshot)
    scope = _scope_for_player(sample_turn, next(row.ownerid for row in sample_turn.scores))
    scope = ComputeScope(
        analytic_id=_FLEET_ANALYTIC_ID,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn=scope.turn,
        player_id=scope.player_id,
    )
    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if handle.state == "complete":
            break
        time.sleep(0.01)
    pool.shutdown()
    assert handle.state == "complete", handle.error
    assert len(snapshots) == 1
    assert built == snapshots
    assert built[0]["dependency_outputs"] is snapshots[0]["dependency_outputs"]
    assert pool.metrics.thread_executions == 1
    assert pool.metrics.interpreter_executions == 0
