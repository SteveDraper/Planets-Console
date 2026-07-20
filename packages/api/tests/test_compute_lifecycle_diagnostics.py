"""Causal lifecycle events on the compute concurrency timeline."""

from __future__ import annotations

import pytest
from api.compute import (
    ComputeOrchestrator,
    ComputeRequest,
    build_compute_registry,
)
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
    snapshot_to_wire,
)
from api.compute.errors import ComputeScopeAbortedError
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
from api.compute.wire import StepResult
from api.config import ApiConfig, set_config

from tests.fixtures.export_framework.diamond_exports import BRANCH_B_ID, SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)
from tests.test_compute_foundation import _StubPersistencePolicy
from tests.test_compute_orchestrator import (
    _compute_scope,
    _export_scope,
    _pool_compute_registration,
    _RecordingPersistencePolicy,
)


@pytest.fixture(autouse=True)
def _reset_compute_diagnostics_state():
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


def test_force_fresh_replace_and_stale_pool_finish_appear_on_timeline(sample_turn):
    """force_fresh replace + ignored pool finish are visible in concurrencyTimeline."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    pool_submissions: list[object] = []

    def pool_submitter(node, step) -> None:
        del step
        pool_submissions.append(node.scope)

    registry = build_compute_registry((_pool_compute_registration(SHARED_ID, backend="thread"),))
    orchestrator = ComputeOrchestrator(
        compute_registry=registry,
        pool_submitter=pool_submitter,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=shared_scope.game_id,
        perspective=shared_scope.perspective,
        turn=shared_scope.turn,
    )
    controller.on_shell_context(shell)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    assert orchestrator.nodes[shared_scope].state == "running"
    orchestrator.complete_pool_step(
        shared_scope,
        result_wire={"result": SHARED_ID},
        step_kind="materialize",
        step_index=0,
    )
    assert orchestrator.nodes[shared_scope].state == "complete"

    orchestrator.submit(
        ComputeRequest(ctx=ctx, scope=shared_scope, force_fresh=True, step_kind="materialize")
    )
    assert orchestrator.nodes[shared_scope].state == "running"

    orchestrator.abort_scope(shared_scope, ComputeScopeAbortedError("cancelled"))
    orchestrator.complete_pool_step(
        shared_scope,
        result_wire={"result": "stale"},
        step_kind="materialize",
        step_index=0,
    )

    wire = snapshot_to_wire(controller.snapshot(shell))
    kinds = [event["kind"] for event in wire["concurrencyTimeline"]]
    assert "force_fresh_replace" in kinds
    assert "abort" in kinds
    assert "pool_finish_ignored" in kinds

    replace = next(e for e in wire["concurrencyTimeline"] if e["kind"] == "force_fresh_replace")
    assert replace["detail"]["reason"] == "submit_force_fresh"
    assert replace["detail"]["priorState"] == "complete"
    assert replace["stepIndex"] == 0

    abort = next(e for e in wire["concurrencyTimeline"] if e["kind"] == "abort")
    assert abort["stepKind"] == "materialize"
    assert abort["stepIndex"] == 0

    ignored = next(e for e in wire["concurrencyTimeline"] if e["kind"] == "pool_finish_ignored")
    assert ignored["detail"]["reason"] == "node_not_running"
    assert ignored["stepKind"] == "materialize"
    assert ignored["stepIndex"] == 0


def test_persist_deferred_lifecycle_event_includes_related_scope(sample_turn):
    """PersistDeferredError records persist_deferred then force_fresh on the dependency."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
    recovery = PersistDependencyRecovery(
        dependency_scope=shared_scope,
        force_fresh=True,
        step_kind="materialize",
    )

    class _DeferredOncePersistence(_StubPersistencePolicy):
        def __init__(self) -> None:
            self.calls = 0

        def persist(self, _ctx, scope, result_wire):
            del scope, result_wire
            self.calls += 1
            if self.calls == 1:
                raise PersistDeferredError(
                    "dependency evidence still open",
                    recovery=recovery,
                )

    deferred_persistence = _DeferredOncePersistence()
    pool_submissions: list[object] = []

    def pool_submitter(node, step) -> None:
        del step
        pool_submissions.append(node.scope)

    registry = build_compute_registry(
        (
            _pool_compute_registration(SHARED_ID, backend="thread"),
            _pool_compute_registration(
                BRANCH_B_ID,
                backend="thread",
                persistence_policy=deferred_persistence,
            ),
        )
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=registry,
        pool_submitter=pool_submitter,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=shared_scope.game_id,
        perspective=shared_scope.perspective,
        turn=shared_scope.turn,
    )
    controller.on_shell_context(shell)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=branch_b_scope))
    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})
    orchestrator.complete_pool_step(
        branch_b_scope,
        result_wire=StepResult(outcome="persist", payload={"result": BRANCH_B_ID}),
    )

    wire = snapshot_to_wire(controller.snapshot(shell))
    deferred = [e for e in wire["concurrencyTimeline"] if e["kind"] == "persist_deferred"]
    assert deferred
    assert deferred[0]["detail"]["relatedScopeKey"].startswith(f"{SHARED_ID}@")
    assert deferred[0]["stepIndex"] == 0
    assert any(e["kind"] == "force_fresh_replace" for e in wire["concurrencyTimeline"])


def test_epoch_retry_lifecycle_event_reports_canonical_step_index(sample_turn):
    """Stale-epoch retry reports the retried step via the canonical stepIndex field."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    persistence = _RecordingPersistencePolicy()

    def pool_submitter(node, step) -> None:
        del node, step

    registry = build_compute_registry(
        (_pool_compute_registration(SHARED_ID, backend="thread", persistence_policy=persistence),)
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=registry,
        pool_submitter=pool_submitter,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=shared_scope.game_id,
        perspective=shared_scope.perspective,
        turn=shared_scope.turn,
    )
    controller.on_shell_context(shell)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    persistence.invalidate(ctx, shared_scope)
    orchestrator.complete_pool_step(shared_scope, result_wire={"result": SHARED_ID})

    wire = snapshot_to_wire(controller.snapshot(shell))
    retried = next(e for e in wire["concurrencyTimeline"] if e["kind"] == "epoch_retry")
    assert retried["detail"]["reason"] == "invalidation_generation_bump"
    assert retried["stepIndex"] == 0


def test_step_parked_lifecycle_event_reports_canonical_step_index(sample_turn):
    """Soft-park reports the parked step via the canonical stepIndex field."""
    ctx = make_fixture_query_context(
        sample_turn,
        registry=DIAMOND_FIXTURE_EXPORT_REGISTRY,
    )
    export_scope = _export_scope(sample_turn)
    shared_scope = _compute_scope(SHARED_ID, export_scope)

    def pool_submitter(node, step) -> None:
        del node, step

    registry = build_compute_registry((_pool_compute_registration(SHARED_ID, backend="thread"),))
    orchestrator = ComputeOrchestrator(
        compute_registry=registry,
        pool_submitter=pool_submitter,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=shared_scope.game_id,
        perspective=shared_scope.perspective,
        turn=shared_scope.turn,
    )
    controller.on_shell_context(shell)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared_scope))
    orchestrator.complete_pool_step(
        shared_scope,
        result_wire=StepResult(outcome="park", park_reason="test_park"),
    )

    wire = snapshot_to_wire(controller.snapshot(shell))
    parked = next(e for e in wire["concurrencyTimeline"] if e["kind"] == "step_parked")
    assert parked["detail"]["reason"] == "test_park"
    assert parked["stepIndex"] == 0
