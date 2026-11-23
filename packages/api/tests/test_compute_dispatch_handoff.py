"""Dispatch-pass and hand-off exception safety.

A node becomes ``running`` only once its work record exists, and every
record a pass commits reaches an inline run or the pool. A raise while one
node is prepared fails that node and the pass carries on. A raise while one
item is handed off fails only that item's own attempt, and the rest of the
pass's work still runs.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry

from tests.compute_orchestrator_fixtures import (
    RecordingPersistencePolicy,
    RecordingPoolSubmitter,
    StubPersistencePolicy,
    inline_compute_registration,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)


class _PrepareError(RuntimeError):
    pass


class _RaisingGenerationPolicy(StubPersistencePolicy):
    """Never satisfied; reading the invalidation generation of ``failing_scope`` raises."""

    def __init__(self, failing_scope) -> None:
        self.failing_scope = failing_scope

    def invalidation_generation(self, _ctx, scope) -> int:
        if scope == self.failing_scope:
            raise _PrepareError("generation read failed")
        return 0


def _two_shared_scopes(sample_turn):
    export_scope = make_export_scope(sample_turn)
    first = make_compute_scope(SHARED_ID, export_scope)
    second = make_compute_scope(SHARED_ID, replace(export_scope, perspective=2))
    return first, second


def _ctx(sample_turn):
    return make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)


def _hold_and_submit(orchestrator: ComputeOrchestrator, ctx, scopes) -> None:
    """Submit ``scopes`` while a gate holds dispatch, then lift the gate.

    Each scope is left ``ready``, so the next pass sees all of them.
    """
    release = orchestrator.observers.register_dispatch_gate(lambda _node: False)
    for scope in scopes:
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    release()


def _inline_shared(persistence_policy) -> ComputeOrchestrator:
    registration = replace(
        inline_compute_registration(SHARED_ID),
        persistence_policy=persistence_policy,
    )
    return ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))


def test_a_generation_read_that_raises_fails_that_node_and_the_pass_continues(sample_turn):
    first, second = _two_shared_scopes(sample_turn)
    orchestrator = _inline_shared(_RaisingGenerationPolicy(failing_scope=first))
    _hold_and_submit(orchestrator, _ctx(sample_turn), (first, second))

    orchestrator.dispatch_ready_work()

    assert orchestrator.nodes[first].state == "failed"
    assert isinstance(orchestrator.nodes[first].error, _PrepareError)
    assert orchestrator.nodes[second].state == "complete"


def test_a_wire_snapshot_that_raises_fails_that_node_and_the_pass_continues(
    sample_turn, monkeypatch
):
    first, second = _two_shared_scopes(sample_turn)
    orchestrator = _inline_shared(StubPersistencePolicy())
    _hold_and_submit(orchestrator, _ctx(sample_turn), (first, second))
    real_snapshot = orchestrator._snapshot_job_wire_kwargs

    def snapshot(node):
        if node.scope == first:
            raise _PrepareError("snapshot failed")
        return real_snapshot(node)

    monkeypatch.setattr(orchestrator, "_snapshot_job_wire_kwargs", snapshot)

    orchestrator.dispatch_ready_work()

    assert orchestrator.nodes[first].state == "failed"
    assert isinstance(orchestrator.nodes[first].error, _PrepareError)
    assert orchestrator.nodes[second].state == "complete"


class _ListenerError(RuntimeError):
    pass


def test_an_inline_start_listener_that_raises_fails_only_that_item(sample_turn):
    first, second = _two_shared_scopes(sample_turn)
    orchestrator = _inline_shared(StubPersistencePolicy())
    _hold_and_submit(orchestrator, _ctx(sample_turn), (first, second))

    def on_inline_start(scope, _node, _step_kind) -> None:
        if scope == first:
            raise _ListenerError("inline start listener failed")

    orchestrator.observers.register_inline_start_listener(on_inline_start)

    orchestrator.dispatch_ready_work()

    assert orchestrator.nodes[first].state == "failed"
    assert isinstance(orchestrator.nodes[first].error, _ListenerError)
    assert orchestrator.nodes[second].state == "complete"


def test_a_finish_that_raises_after_an_epoch_requeue_leaves_the_retry_running(sample_turn):
    scope, _other = _two_shared_scopes(sample_turn)
    persistence = RecordingPersistencePolicy()
    ctx = _ctx(sample_turn)
    stale_once = [True]

    def run_step(job):
        if stale_once[0]:
            stale_once[0] = False
            persistence.invalidate(ctx, scope)
        return {"result": job["scope"]}

    registration = replace(
        inline_compute_registration(SHARED_ID),
        persistence_policy=persistence,
        run_steps=(("materialize", run_step),),
    )
    orchestrator = ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))
    # The first time the scope is queued is the submission; the second is the
    # epoch requeue inside the inline finish.
    times_queued = [0]

    def on_ready_queue_changed(ready_scopes) -> None:
        if scope not in ready_scopes:
            return
        times_queued[0] += 1
        if times_queued[0] == 2:
            raise _ListenerError("ready-queue listener failed during the requeue")

    orchestrator.observers.register_ready_queue_listener(on_ready_queue_changed)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    orchestrator.dispatch_ready_work()

    node = orchestrator.nodes[scope]
    assert node.error is None
    assert node.state == "complete"
    assert orchestrator.metrics.epoch_discards == 1


def test_a_pool_submitter_that_raises_fails_its_node(sample_turn):
    scope, _other = _two_shared_scopes(sample_turn)
    submitter = RecordingPoolSubmitter(raise_on_submit=_ListenerError("pool refused the item"))
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (pool_compute_registration(SHARED_ID, backend="thread"),)
        ),
        pool_submitter=submitter,
    )

    orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))

    assert orchestrator.nodes[scope].state == "failed"
    assert isinstance(orchestrator.nodes[scope].error, _ListenerError)


@pytest.mark.allows_post_lock_callback_errors
def test_a_gate_that_raises_mid_pass_still_hands_off_the_work_already_committed(sample_turn):
    first, second = _two_shared_scopes(sample_turn)
    orchestrator = _inline_shared(StubPersistencePolicy())
    _hold_and_submit(orchestrator, _ctx(sample_turn), (first, second))

    def gate(node) -> bool:
        if node.scope == second:
            raise _ListenerError("gate failed")
        return True

    orchestrator.observers.register_dispatch_gate(gate)

    with pytest.raises(_ListenerError):
        orchestrator.dispatch_ready_work()

    assert orchestrator.nodes[first].state == "complete"
    assert orchestrator.nodes[second].state == "ready"
