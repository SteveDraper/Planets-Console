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
from api.compute.orchestrator_pending import DispatchedWork
from api.compute.pools import ComputeWorkerPool
from api.compute.running_step import RunningStepDisposition

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


class _FinishError(RuntimeError):
    pass


class _GenerationFailsAfterRunPolicy(StubPersistencePolicy):
    """Never satisfied; reading the invalidation generation raises once the step has run."""

    def __init__(self) -> None:
        self.has_step_run = False

    def invalidation_generation(self, _ctx, _scope) -> int:
        if self.has_step_run:
            raise _FinishError("generation read failed at the finish")
        return 0


def test_a_finish_that_raises_while_its_execution_runs_fails_the_node(sample_turn):
    scope, _other = _two_shared_scopes(sample_turn)
    persistence = _GenerationFailsAfterRunPolicy()

    def run_step(job):
        persistence.has_step_run = True
        return {"result": job["scope"]}

    registration = replace(
        inline_compute_registration(SHARED_ID),
        persistence_policy=persistence,
        run_steps=(("materialize", run_step),),
    )
    orchestrator = ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))

    orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))

    node = orchestrator.nodes[scope]
    assert node.state == "failed"
    assert isinstance(node.error, _FinishError)


def _epoch_bumping_inline_orchestrator(ctx, scope) -> ComputeOrchestrator:
    """An inline orchestrator whose first run of ``scope`` makes itself epoch-stale."""
    persistence = RecordingPersistencePolicy()
    is_first_run = [True]

    def run_step(job):
        if is_first_run[0]:
            is_first_run[0] = False
            persistence.invalidate(ctx, scope)
        return {"result": job["scope"]}

    registration = replace(
        inline_compute_registration(SHARED_ID),
        persistence_policy=persistence,
        run_steps=(("materialize", run_step),),
    )
    return ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))


class _HandOffError(RuntimeError):
    pass


def test_a_hand_off_failure_after_the_finish_applied_leaves_the_epoch_retry_running(
    sample_turn, monkeypatch
):
    scope, _other = _two_shared_scopes(sample_turn)
    ctx = _ctx(sample_turn)
    orchestrator = _epoch_bumping_inline_orchestrator(ctx, scope)
    real_run_inline = orchestrator._run_inline_outside_lock
    retry_work = DispatchedWork()

    def run_inline_then_fail_once_the_retry_runs(item) -> None:
        real_run_inline(item)
        if retry_work.inline:
            return
        # The finish requeued the epoch-stale step; dispatch the retry so it
        # runs the same execution and step index, then fail this hand-off.
        with orchestrator._condition:
            orchestrator._dispatch(retry_work)
        raise _HandOffError("hand-off failed after the finish applied")

    monkeypatch.setattr(
        orchestrator, "_run_inline_outside_lock", run_inline_then_fail_once_the_retry_runs
    )

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))

    node = orchestrator.nodes[scope]
    assert len(retry_work.inline) == 1
    assert node.state == "running"
    assert node.error is None
    assert orchestrator.metrics.epoch_discards == 1

    orchestrator._hand_off(retry_work)

    assert node.state == "complete"
    assert node.error is None


def test_a_ready_queue_listener_that_raises_on_an_epoch_requeue_strands_the_node_ready(
    sample_turn,
):
    """The requeue raises before it schedules a pass, so nothing dispatches the retry.

    The finish's own containment swallows the error and leaves the node
    ``ready``, which is the synchronous ready-queue listener failure policy
    owned by #650. This pins that the original attempt does not fail the node.
    """
    scope, _other = _two_shared_scopes(sample_turn)
    ctx = _ctx(sample_turn)
    orchestrator = _epoch_bumping_inline_orchestrator(ctx, scope)
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

    node = orchestrator.nodes[scope]
    assert node.error is None
    assert node.state == "ready"
    assert orchestrator.ready_scopes() == (scope,)
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


def test_an_enqueue_hook_that_raises_leaves_the_accepted_pool_item_queued_and_running(
    sample_turn,
):
    scope, _other = _two_shared_scopes(sample_turn)
    pool = ComputeWorkerPool(worker_count=0)

    def on_enqueued(_item, _depth) -> None:
        raise _ListenerError("enqueue hook failed")

    pool.set_on_item_enqueued(on_enqueued)
    try:
        orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry(
                (pool_compute_registration(SHARED_ID, backend="thread"),)
            ),
            worker_pool=pool,
        )

        orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))

        assert [queued.item.scope for queued in pool.snapshot_work_queue()] == [scope]
        assert orchestrator.nodes[scope].state == "running"
        assert orchestrator.nodes[scope].error is None
    finally:
        pool.shutdown()


def test_a_hand_off_failure_for_an_accepted_pool_item_leaves_its_node_running(
    sample_turn, monkeypatch
):
    scope, _other = _two_shared_scopes(sample_turn)
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (pool_compute_registration(SHARED_ID, backend="thread"),)
        ),
        pool_submitter=RecordingPoolSubmitter(),
    )
    accepted = []
    real_flush = orchestrator._flush_pending_pool_submissions

    def flush_and_keep(pending) -> None:
        real_flush(pending)
        accepted.extend(pending)

    monkeypatch.setattr(orchestrator, "_flush_pending_pool_submissions", flush_and_keep)
    orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))
    assert len(accepted) == 1

    orchestrator._fail_running_step(accepted[0], "pool", _HandOffError("late failure"))

    assert orchestrator.nodes[scope].state == "running"
    assert orchestrator.nodes[scope].error is None


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


class _SatisfiedPolicy(StubPersistencePolicy):
    """Durable satisfaction already holds for every scope."""

    def is_satisfied(self, _ctx, _scope) -> bool:
        return True


def test_a_satisfied_node_that_nothing_needs_completes_rather_than_being_stopped_at_start(
    sample_turn,
):
    """The satisfaction short-circuit is prepared before the START gate.

    A ready node whose running step is limited to ``END_AFTER_STEP`` (left by
    a settle while it ran) and that nothing needs would be refused a start,
    but its durable result is already there, so it completes without running.
    """
    scope, _other = _two_shared_scopes(sample_turn)
    step_runs: list[object] = []

    def run_step(job):
        step_runs.append(job)
        return {"result": job["scope"]}

    registration = replace(
        inline_compute_registration(SHARED_ID),
        persistence_policy=_SatisfiedPolicy(),
        run_steps=(("materialize", run_step),),
    )
    orchestrator = ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))
    _hold_and_submit(orchestrator, _ctx(sample_turn), (scope,))
    node = orchestrator.nodes[scope]
    node.running_step = RunningStepDisposition.END_AFTER_STEP

    orchestrator.dispatch_ready_work()

    assert node.state == "complete"
    assert node.error is None
    assert orchestrator.metrics.satisfaction_short_circuits == 1
    assert step_runs == []
