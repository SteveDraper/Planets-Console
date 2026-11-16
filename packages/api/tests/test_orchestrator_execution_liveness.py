"""Work a node queued or picked runs only while that node's execution is live.

A dependency submit that a node queues post-lock carries the node's
execution as its requester. The orchestrator refuses it, planning nothing,
once that execution has ended, including when it ends while the submit
fetches its dependency chain. Each refusal records one
``dependency_submit_refused`` lifecycle event on the requester's execution.
A thread pool step whose execution ends while its wire builds, or whose
start-or-requeue gate refuses it then, is dropped before it runs.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeStepSpec,
    ComputeWorkerPool,
    PoolWorkItem,
    build_compute_registry,
)
from api.compute.errors import ComputeScopeAbortedError
from api.compute.in_flight_settle import GameWork, RunningDisposition
from api.compute.orchestrator_observers import STEP_ITEM_IGNORED_KINDS, StepItemIgnoredReason
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
from api.compute.scope import format_compute_scope_key
from api.compute.wire import StepResult

from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import BRANCH_B_ID, SHARED_ID
from tests.fixtures.export_framework.fixture_catalog import make_fixture_catalog
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)
from tests.test_compute_foundation import _StubPersistencePolicy
from tests.test_compute_orchestrator import (
    _compute_scope,
    _export_scope,
    _pool_compute_registration,
)
from tests.test_compute_pools import (
    _ANALYTIC_ID,
    _POOL_EXPORT_REGISTRY,
    _ROW_SCOPE_KEY,
    _catalog_entry,
    _scope_for_player,
)
from tests.test_orchestrator_settle import _StopEverything

_ABORT = ComputeScopeAbortedError("requester cancelled")


class _DeferredOncePersistence(_StubPersistencePolicy):
    """Defers the first persist onto ``recovery``'s dependency, then persists."""

    def __init__(self, recovery: PersistDependencyRecovery) -> None:
        self.recovery = recovery
        self.calls = 0

    def persist(self, _ctx, scope, result_wire):
        del scope, result_wire
        self.calls += 1
        if self.calls == 1:
            raise PersistDeferredError("dependency evidence still open", recovery=self.recovery)


class _PersistDeferredHarness:
    """``branch_b`` depends on ``shared``; its first persist defers onto ``shared``.

    The deferral demotes ``branch_b`` to ``waiting_deps`` and queues a
    post-lock ``force_fresh`` submit of the completed ``shared`` scope, which
    plans a new execution of ``shared``.
    """

    def __init__(self, sample_turn) -> None:
        self.ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
        export_scope = _export_scope(sample_turn)
        self.shared_scope = _compute_scope(SHARED_ID, export_scope)
        self.branch_b_scope = _compute_scope(BRANCH_B_ID, export_scope)
        self.persistence = _DeferredOncePersistence(
            PersistDependencyRecovery(
                dependency_scope=self.shared_scope,
                force_fresh=True,
                step_kind="materialize",
            )
        )
        self.pool_submissions: list[ComputeScope] = []
        self.orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry(
                (
                    _pool_compute_registration(SHARED_ID, backend="thread"),
                    _pool_compute_registration(
                        BRANCH_B_ID,
                        backend="thread",
                        persistence_policy=self.persistence,
                    ),
                )
            ),
            pool_submitter=lambda node, _step, **_kwargs: self.pool_submissions.append(node.scope),
        )
        self.refusals: list[tuple[ComputeScope, int, ComputeNodeRun | None, dict[str, object]]] = []
        self.orchestrator.observers.register_lifecycle_listener(self._record_refusal)

    def _record_refusal(self, kind, scope, node, generation, _step_kind, _step_index, detail):
        if kind == "dependency_submit_refused":
            self.refusals.append((scope, generation, node, dict(detail)))

    def assert_one_refused_shared_submit(self, *, dependency_step_kind: str | None) -> None:
        """One refusal names the aborted ``branch_b`` execution and the refused ``shared``."""
        requester = self.node(self.branch_b_scope)
        assert self.refusals == [
            (
                self.branch_b_scope,
                requester.execution_generation,
                requester,
                {
                    "reason": "requester_ended",
                    "relatedScopeKey": format_compute_scope_key(self.shared_scope),
                    "dependencyStepKind": dependency_step_kind,
                    "forceFresh": True,
                },
            )
        ]

    def run_branch_b_to_its_persist(self) -> ComputeNodeRun:
        """Run ``shared`` to complete and ``branch_b`` to running; return the ``shared`` node."""
        self.orchestrator.submit(ComputeRequest(ctx=self.ctx, scope=self.branch_b_scope))
        complete_running_pool_step(
            self.orchestrator, self.shared_scope, result_wire={"result": SHARED_ID}
        )
        assert self.node(self.branch_b_scope).state == "running"
        completed_shared = self.node(self.shared_scope)
        assert completed_shared.state == "complete"
        self.pool_submissions.clear()
        return completed_shared

    def finish_branch_b_with_persist(self) -> None:
        """Finish ``branch_b``'s step with a persist, which the policy defers."""
        complete_running_pool_step(
            self.orchestrator,
            self.branch_b_scope,
            result_wire=StepResult(outcome="persist", payload={"result": BRANCH_B_ID}),
        )

    def abort_branch_b(self) -> None:
        assert self.orchestrator.abort_scope(self.branch_b_scope, _ABORT)

    def node(self, scope: ComputeScope) -> ComputeNodeRun:
        return self.orchestrator.nodes[scope]


def test_t11a_persist_deferred_recovery_submits_its_dependency_while_the_requester_is_live(
    sample_turn,
):
    harness = _PersistDeferredHarness(sample_turn)
    completed_shared = harness.run_branch_b_to_its_persist()

    harness.finish_branch_b_with_persist()

    assert harness.persistence.calls == 1
    assert harness.node(harness.branch_b_scope).state == "waiting_deps"
    replanned_shared = harness.node(harness.shared_scope)
    assert replanned_shared is not completed_shared
    assert replanned_shared.execution_generation > completed_shared.execution_generation
    assert replanned_shared.state == "running"
    assert harness.pool_submissions == [harness.shared_scope]
    assert harness.refusals == []


def test_t11b_an_abort_before_the_queued_dependency_submit_plans_nothing(sample_turn, monkeypatch):
    harness = _PersistDeferredHarness(sample_turn)
    completed_shared = harness.run_branch_b_to_its_persist()
    submit = harness.orchestrator.submit

    def abort_requester_then_submit(request: ComputeRequest):
        if request.scope == harness.shared_scope:
            harness.abort_branch_b()
        return submit(request)

    monkeypatch.setattr(harness.orchestrator, "submit", abort_requester_then_submit)

    harness.finish_branch_b_with_persist()

    assert harness.node(harness.branch_b_scope).error is _ABORT
    assert harness.node(harness.shared_scope) is completed_shared
    assert completed_shared.state == "complete"
    assert harness.pool_submissions == []
    harness.assert_one_refused_shared_submit(dependency_step_kind="materialize")


def test_a_refusal_after_the_requester_was_replaced_names_no_node(sample_turn, monkeypatch):
    harness = _PersistDeferredHarness(sample_turn)
    harness.run_branch_b_to_its_persist()
    ended_generation = harness.node(harness.branch_b_scope).execution_generation
    submit = harness.orchestrator.submit

    def replace_requester_then_submit(request: ComputeRequest):
        if request.scope == harness.shared_scope:
            harness.abort_branch_b()
            submit(ComputeRequest(ctx=harness.ctx, scope=harness.branch_b_scope, force_fresh=True))
        return submit(request)

    monkeypatch.setattr(harness.orchestrator, "submit", replace_requester_then_submit)

    harness.finish_branch_b_with_persist()

    assert harness.node(harness.branch_b_scope).execution_generation > ended_generation
    assert [(scope, generation, node) for scope, generation, node, _ in harness.refusals] == [
        (harness.branch_b_scope, ended_generation, None)
    ]


def test_t11c_an_abort_during_the_dependency_chain_fetch_plans_nothing(sample_turn, monkeypatch):
    harness = _PersistDeferredHarness(sample_turn)
    completed_shared = harness.run_branch_b_to_its_persist()
    fetch_started = threading.Event()
    abort_landed = threading.Event()

    def blocking_chain_fetch(*_args, **_kwargs) -> None:
        fetch_started.set()
        assert abort_landed.wait(timeout=5.0)

    monkeypatch.setattr(
        "api.compute.orchestrator_submission.prepare_dependency_chain_turns",
        blocking_chain_fetch,
    )
    finisher = threading.Thread(target=harness.finish_branch_b_with_persist)
    finisher.start()
    try:
        assert fetch_started.wait(timeout=5.0)
        harness.abort_branch_b()
    finally:
        abort_landed.set()
        finisher.join(timeout=5.0)

    assert not finisher.is_alive()
    assert harness.node(harness.branch_b_scope).error is _ABORT
    assert harness.node(harness.shared_scope) is completed_shared
    assert completed_shared.state == "complete"
    assert harness.pool_submissions == []
    harness.assert_one_refused_shared_submit(dependency_step_kind="materialize")


def test_recreating_an_abort_failed_dependency_plans_nothing_once_its_requester_ended(
    sample_turn, monkeypatch
):
    harness = _PersistDeferredHarness(sample_turn)
    harness.run_branch_b_to_its_persist()
    harness.finish_branch_b_with_persist()
    assert harness.orchestrator.abort_scope(harness.shared_scope, _ABORT)
    aborted_shared = harness.node(harness.shared_scope)
    harness.pool_submissions.clear()
    submit = harness.orchestrator.submit

    def abort_requester_then_submit(request: ComputeRequest):
        if request.scope == harness.shared_scope:
            harness.abort_branch_b()
        return submit(request)

    monkeypatch.setattr(harness.orchestrator, "submit", abort_requester_then_submit)

    # A force_fresh attach of the waiting dependent queues the recreate submit.
    submit(ComputeRequest(ctx=harness.ctx, scope=harness.branch_b_scope, force_fresh=True))

    assert harness.node(harness.branch_b_scope).error is _ABORT
    assert harness.node(harness.shared_scope) is aborted_shared
    assert harness.pool_submissions == []
    harness.assert_one_refused_shared_submit(dependency_step_kind=None)


def _thread_registration(
    build_wire: Callable[..., object],
    run_step: Callable[[object], object],
) -> TurnAnalyticRegistration:
    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(),
        compute=lambda _ctx: {"analyticId": _ANALYTIC_ID},
        export_catalog=make_fixture_catalog(_ANALYTIC_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="thread"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(("materialize", build_wire),),
        run_steps=(("materialize", run_step),),
    )


class _ThreadStepHarness:
    """A worker-less pool whose one thread step the test picks and runs by hand."""

    def __init__(self, sample_turn, *, on_build: Callable[[], None]) -> None:
        self.run_step_calls = 0
        self.on_build = on_build
        self.pool = ComputeWorkerPool(worker_count=0)
        self.orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry(
                (_thread_registration(self._build_wire, self._run_step),)
            ),
            worker_pool=self.pool,
        )
        self.ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
        self.scope = _scope_for_player(sample_turn, next(row.ownerid for row in sample_turn.scores))
        self.finished_items: list[PoolWorkItem] = []
        self.pool.set_on_item_finished(self.finished_items.append)
        self.ignored: list[tuple[str, str]] = []
        self.orchestrator.observers.register_lifecycle_listener(self._record_ignored)

    def _build_wire(self, _scope, **_kwargs) -> dict[str, object]:
        self.on_build()
        return {}

    def _run_step(self, _job: object) -> dict[str, bool]:
        self.run_step_calls += 1
        return {"ok": True}

    def _record_ignored(self, kind, _scope, _node, _generation, _step_kind, _step_index, detail):
        if kind in STEP_ITEM_IGNORED_KINDS:
            self.ignored.append((kind, detail["reason"]))

    def submit_and_run_picked_step(self) -> None:
        self.orchestrator.submit(ComputeRequest(ctx=self.ctx, scope=self.scope))
        picked = self.pool.take_next_item_for_tests()
        assert picked is not None
        self.pool._execute_item(picked)

    def node(self) -> ComputeNodeRun:
        return self.orchestrator.nodes[self.scope]


@pytest.fixture
def make_thread_harness(sample_turn):
    harnesses: list[_ThreadStepHarness] = []

    def make(on_build: Callable[[], None]) -> _ThreadStepHarness:
        harness = _ThreadStepHarness(sample_turn, on_build=on_build)
        harnesses.append(harness)
        return harness

    yield make
    for harness in harnesses:
        harness.pool.shutdown()


def test_t12_a_thread_step_whose_execution_ends_while_its_wire_builds_never_runs(
    make_thread_harness,
):
    def abort_during_build() -> None:
        assert harness.orchestrator.abort_scope(harness.scope, _ABORT)

    harness = make_thread_harness(abort_during_build)

    harness.submit_and_run_picked_step()

    assert harness.run_step_calls == 0
    assert harness.node().error is _ABORT
    assert harness.ignored == [("pool_item_dropped", "node_not_running")]
    assert len(harness.finished_items) == 1


def test_a_thread_step_its_start_gate_refuses_while_its_wire_builds_never_runs(
    make_thread_harness,
):
    def stop_during_build() -> None:
        harness.orchestrator.settle_in_flight_work(
            GameWork(game_id=harness.scope.game_id, analytic_ids=frozenset({_ANALYTIC_ID})),
            _StopEverything(RunningDisposition.END_AFTER_STEP),
        )

    harness = make_thread_harness(stop_during_build)

    harness.submit_and_run_picked_step()

    assert harness.run_step_calls == 0
    assert isinstance(harness.node().error, ComputeScopeAbortedError)
    assert harness.ignored == [("pool_item_dropped", StepItemIgnoredReason.START_REFUSED)]
    assert len(harness.finished_items) == 1


def test_a_thread_step_whose_wire_build_raises_fails_its_node(make_thread_harness):
    build_error = RuntimeError("wire build failed")

    def raise_build_error() -> None:
        raise build_error

    harness = make_thread_harness(raise_build_error)

    harness.submit_and_run_picked_step()

    assert harness.run_step_calls == 0
    assert harness.node().error is build_error
    assert harness.ignored == []
    assert len(harness.finished_items) == 1


def test_a_thread_step_whose_execution_stays_live_runs_and_completes(make_thread_harness):
    harness = make_thread_harness(lambda: None)

    harness.submit_and_run_picked_step()

    assert harness.run_step_calls == 1
    assert harness.node().state == "complete"
    assert harness.ignored == []
    assert len(harness.finished_items) == 1
