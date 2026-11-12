"""Causal lifecycle events on the compute concurrency timeline, and the open starts
that a pool step's finish releases."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import replace

import pytest
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    COMPUTE_REGISTRY,
    BandedWorkItem,
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
from api.compute.diagnostics.timeline import format_execution_key
from api.compute.errors import ComputeScopeAbortedError
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
from api.compute.pools import (
    reset_compute_worker_pool_for_tests,
    shutdown_compute_worker_pool_for_tests,
)
from api.compute.wire import StepResult
from api.config import ApiConfig, set_config

from tests.compute_pool_test_helpers import complete_running_pool_step
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
from tests.test_compute_pools import (
    _POOL_EXPORT_REGISTRY,
    _multi_step_thread_registration,
    _scope_for_player,
)
from tests.test_compute_stale_pool_item import _generation_echo_registration, _ManualRemoteExecutor


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

    def pool_submitter(node, step, **_kwargs) -> None:
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
    complete_running_pool_step(
        orchestrator,
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
    complete_running_pool_step(
        orchestrator,
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

    def pool_submitter(node, step, **_kwargs) -> None:
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
    complete_running_pool_step(orchestrator, shared_scope, result_wire={"result": SHARED_ID})
    complete_running_pool_step(
        orchestrator,
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

    def pool_submitter(node, step, **_kwargs) -> None:
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
    complete_running_pool_step(orchestrator, shared_scope, result_wire={"result": SHARED_ID})

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

    def pool_submitter(node, step, **_kwargs) -> None:
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
    complete_running_pool_step(
        orchestrator,
        shared_scope,
        result_wire=StepResult(outcome="park", park_reason="test_park"),
    )

    wire = snapshot_to_wire(controller.snapshot(shell))
    parked = next(e for e in wire["concurrencyTimeline"] if e["kind"] == "step_parked")
    assert parked["detail"]["reason"] == "test_park"
    assert parked["stepIndex"] == 0


class _PoolStepUnderShell:
    """One scope on a worker-less diagnosed pool, submitted under its own operator shell.

    Remote steps run on a manual interpreter executor, so the test decides when
    each one finishes.
    """

    def __init__(self, sample_turn, registration: TurnAnalyticRegistration) -> None:
        self.pool = reset_compute_worker_pool_for_tests(worker_count=0)
        self.executor = _ManualRemoteExecutor()
        self.pool._interpreter_executor = self.executor  # type: ignore[assignment]
        self.orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry((registration,)),
            worker_pool=self.pool,
        )
        self.scope = _scope_for_player(sample_turn, sample_turn.scores[0].ownerid)
        self.controller = get_compute_diagnostics_controller()
        self.controller.bind_orchestrator(self.orchestrator)
        self.shell = ShellContextKey(
            game_id=self.scope.game_id,
            perspective=self.scope.perspective,
            turn=self.scope.turn,
        )
        self.controller.on_shell_context(self.shell)
        ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
        self.orchestrator.submit(ComputeRequest(ctx=ctx, scope=self.scope))

    def start(self) -> BandedWorkItem:
        """Pick the queued item, which records its timeline start."""
        picked = self.pool.take_next_item_for_tests()
        assert picked is not None
        return picked

    def abort(self) -> None:
        assert self.orchestrator.abort_scope(self.scope, ComputeScopeAbortedError("cancelled"))

    def switch_shell(self) -> None:
        """Move the operator to a shell whose diagnostic scope excludes the step."""
        self.controller.on_shell_context(
            replace(self.shell, perspective=self.shell.perspective + 1)
        )

    def timeline_kinds(self, picked: BandedWorkItem) -> list[str]:
        """Kinds of the starting shell's timeline events naming ``picked``'s execution."""
        execution_key = format_execution_key(picked.item.step_key)
        return [
            event.kind
            for event in self.controller.timeline_recent(self.shell)
            if event.execution_key == execution_key
        ]

    def holds_open_start(self, picked: BandedWorkItem) -> bool:
        return self.controller._timeline._open_executions.close(picked.item.step_key) is not None


@pytest.fixture
def make_pool_step(
    sample_turn,
) -> Iterator[Callable[[TurnAnalyticRegistration], _PoolStepUnderShell]]:
    yield lambda registration: _PoolStepUnderShell(sample_turn, registration)
    shutdown_compute_worker_pool_for_tests()


def _remote_step(make_pool_step) -> _PoolStepUnderShell:
    return make_pool_step(_generation_echo_registration("interpreter", []))


# Each finish runs ``after_start`` between the step's start and its finish.
_PoolStepFinish = Callable[[_PoolStepUnderShell, Callable[[], None]], BandedWorkItem]


def _complete(step: _PoolStepUnderShell, after_start: Callable[[], None]) -> BandedWorkItem:
    picked = step.start()
    step.pool._execute_item(picked)
    after_start()
    step.executor.finish(0)
    return picked


def _fail(step: _PoolStepUnderShell, after_start: Callable[[], None]) -> BandedWorkItem:
    picked = step.start()
    step.pool._execute_item(picked)
    after_start()
    step.executor.fail(0, RuntimeError("step failed"))
    return picked


def _finish_late(step: _PoolStepUnderShell, after_start: Callable[[], None]) -> BandedWorkItem:
    picked = step.start()
    step.pool._execute_item(picked)
    after_start()
    step.abort()
    step.executor.finish(0)
    return picked


def _drop(step: _PoolStepUnderShell, after_start: Callable[[], None]) -> BandedWorkItem:
    step.abort()
    picked = step.start()
    after_start()
    step.pool._execute_item(picked)
    return picked


_POOL_STEP_FINISHES = pytest.mark.parametrize(
    ("finish", "finish_kind"),
    [
        (_complete, "complete"),
        (_fail, "complete"),
        (_finish_late, "pool_finish_ignored"),
        (_drop, "pool_item_dropped"),
    ],
    ids=["complete", "error", "late_finish", "drop"],
)


@_POOL_STEP_FINISHES
def test_pool_step_finish_after_a_shell_switch_releases_its_open_start(
    make_pool_step, finish: _PoolStepFinish, finish_kind: str
):
    step = _remote_step(make_pool_step)

    picked = finish(step, step.switch_shell)

    kinds = step.timeline_kinds(picked)
    assert "start" in kinds
    assert finish_kind not in kinds
    assert not step.holds_open_start(picked)


@_POOL_STEP_FINISHES
def test_pool_step_finish_in_its_starting_shell_records_and_releases_its_open_start(
    make_pool_step, finish: _PoolStepFinish, finish_kind: str
):
    step = _remote_step(make_pool_step)

    picked = finish(step, lambda: None)

    kinds = step.timeline_kinds(picked)
    assert "start" in kinds
    assert kinds[-1] == finish_kind
    if finish_kind == "complete":
        (completed,) = (
            event
            for event in step.controller.timeline_recent(step.shell)
            if event.kind == "complete"
        )
        assert completed.duration_ms is not None
        assert completed.priority_band == picked.priority_band
    assert not step.holds_open_start(picked)


def test_pool_step_continuing_into_another_step_kind_releases_its_open_start(
    make_pool_step, monkeypatch
):
    gate = threading.Event()
    gate.set()
    registration = _multi_step_thread_registration([], gate)
    # Diagnostics resolve profile steps from the process registry.
    monkeypatch.setitem(
        COMPUTE_REGISTRY,
        registration.catalog_entry.id,
        build_compute_registry((registration,))[registration.catalog_entry.id],
    )
    step = make_pool_step(registration)

    picked = step.start()
    step.pool._execute_item(picked)

    node = step.orchestrator.nodes[step.scope]
    assert node.step_index == picked.item.step_index + 1
    assert node.profile_step_index == 1
    assert not step.holds_open_start(picked)
