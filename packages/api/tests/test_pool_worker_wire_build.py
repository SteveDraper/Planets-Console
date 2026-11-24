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
from api.compute import (
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeWorkerPool,
    PoolStepWork,
    build_compute_registry,
)
from api.compute.backend_runtime import effective_pool_backend
from api.compute.wire import StepResult
from api.config import ApiConfig, set_config

from tests.compute_orchestrator_fixtures import (
    make_compute_scope,
    make_export_scope,
    pool_step_registration,
)
from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)


def _set_interpreter_remap(monkeypatch, *, is_remapped: bool) -> None:
    set_config(
        ApiConfig(storage_backend="ephemeral", remap_interpreter_backend_to_thread=is_remapped)
    )
    monkeypatch.setattr("api.compute.backend_runtime.process_is_frozen", lambda: False)


def _interpreter_step_registry(build_wire):
    return build_compute_registry(
        (
            pool_step_registration(
                SHARED_ID,
                backend="interpreter",
                build_wire=build_wire,
                run_step=lambda job: StepResult(outcome="complete", payload=job),
            ),
        )
    )


def _interpreter_step_request(sample_turn) -> ComputeRequest:
    return ComputeRequest(
        ctx=make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY),
        scope=make_compute_scope(SHARED_ID, make_export_scope(sample_turn)),
    )


def _submit_interpreter_step(sample_turn, *, pool_submitter, build_wire):
    orchestrator = ComputeOrchestrator(
        compute_registry=_interpreter_step_registry(build_wire),
        pool_submitter=pool_submitter,
    )
    orchestrator.submit(_interpreter_step_request(sample_turn))
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

    pool = ComputeWorkerPool(worker_count=1)
    orchestrator = ComputeOrchestrator(
        compute_registry=_interpreter_step_registry(build_wire), worker_pool=pool
    )
    take_snapshot = orchestrator._snapshot_job_wire_kwargs  # noqa: SLF001

    def record_snapshot(node):
        snapshots.append(take_snapshot(node))
        return snapshots[-1]

    monkeypatch.setattr(orchestrator, "_snapshot_job_wire_kwargs", record_snapshot)
    handle = orchestrator.submit(_interpreter_step_request(sample_turn))
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
