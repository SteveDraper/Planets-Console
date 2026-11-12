"""A pool item is bound to the execution of its scope that dispatched it.

A node aborted while its pool item waits, then replaced by a ``force_fresh``
submit, runs as a newer execution of the same scope. The older execution's
item must neither run its step nor complete the newer node, on the thread
path and on the remote-future path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future

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
from api.compute.orchestrator_observers import POOL_ITEM_IGNORED_KINDS
from api.compute.profile import ComputeBackend

from tests.fixtures.export_framework.fixture_catalog import make_fixture_catalog
from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_foundation import _StubPersistencePolicy
from tests.test_compute_pools import (
    _ANALYTIC_ID,
    _POOL_EXPORT_REGISTRY,
    _ROW_SCOPE_KEY,
    _catalog_entry,
    _scope_for_player,
)


class _ManualRemoteExecutor:
    """Interpreter executor stand-in whose futures the test resolves by hand."""

    def __init__(self) -> None:
        self.submitted: list[tuple[object, Future[object]]] = []

    def submit(self, _run_step: Callable[[object], object], job_wire: object) -> Future[object]:
        future: Future[object] = Future()
        self.submitted.append((job_wire, future))
        return future

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        del wait, cancel_futures

    def finish(self, index: int) -> None:
        """Finish one submitted step with its job wire as the result."""
        job_wire, future = self.submitted[index]
        future.set_result(job_wire)

    def fail(self, index: int, error: Exception) -> None:
        """Finish one submitted step by raising ``error``."""
        _job_wire, future = self.submitted[index]
        future.set_exception(error)


def _generation_echo_registration(
    backend: ComputeBackend,
    thread_runs: list[int],
) -> TurnAnalyticRegistration:
    """One-step registration whose wire and result name the dispatching execution."""

    def run_materialize(job: dict[str, int]) -> dict[str, int]:
        thread_runs.append(job["generation"])
        return job

    return TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(),
        compute=lambda _ctx: {"analyticId": _ANALYTIC_ID},
        export_catalog=make_fixture_catalog(_ANALYTIC_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend=backend),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            (
                "materialize",
                lambda _scope, *, execution_generation, **_kwargs: {
                    "generation": execution_generation
                },
            ),
        ),
        run_steps=(("materialize", run_materialize),),
    )


class _StaleItemHarness:
    """A worker-less pool, one orchestrator on it, and the pool's finish and ignore records."""

    def __init__(self, sample_turn, backend: ComputeBackend) -> None:
        self.thread_runs: list[int] = []
        self.pool = ComputeWorkerPool(worker_count=0)
        self.orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry(
                (_generation_echo_registration(backend, self.thread_runs),)
            ),
            worker_pool=self.pool,
        )
        self.ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
        self.scope: ComputeScope = _scope_for_player(
            sample_turn, next(row.ownerid for row in sample_turn.scores)
        )
        self.finished_items: list[PoolWorkItem] = []
        self.pool.set_on_item_finished(self.finished_items.append)
        self.ignored: list[tuple[str, object]] = []
        self.orchestrator.observers.register_lifecycle_listener(self._record_ignored)
        self.remote_executor = _ManualRemoteExecutor()
        self.pool._interpreter_executor = self.remote_executor  # type: ignore[assignment]

    def _record_ignored(
        self, kind, _scope, _node, _generation, _step_kind, _step_index, detail
    ) -> None:
        if kind in POOL_ITEM_IGNORED_KINDS:
            self.ignored.append((kind, detail["reason"]))

    def submit(self, *, force_fresh: bool = False) -> int:
        """Submit the scope and return the generation of the execution now running."""
        self.orchestrator.submit(
            ComputeRequest(ctx=self.ctx, scope=self.scope, force_fresh=force_fresh)
        )
        node = self.orchestrator.nodes[self.scope]
        assert node.state == "running"
        return node.execution_generation

    def abort_and_replace(self) -> int:
        """Abort the running execution and return its ``force_fresh`` replacement's generation."""
        assert self.orchestrator.abort_scope(self.scope, ComputeScopeAbortedError("cancelled"))
        return self.submit(force_fresh=True)

    def run_next_item(self) -> None:
        """Pick the next queued item and run it as a pool worker would."""
        picked = self.pool.take_next_item_for_tests()
        assert picked is not None
        self.pool._execute_item(picked)

    def node_outcome(self) -> tuple[str, object]:
        node = self.orchestrator.nodes[self.scope]
        return node.state, node.result_wire


@pytest.fixture
def make_harness(sample_turn) -> Iterator[Callable[[ComputeBackend], _StaleItemHarness]]:
    harnesses: list[_StaleItemHarness] = []

    def make(backend: ComputeBackend) -> _StaleItemHarness:
        harness = _StaleItemHarness(sample_turn, backend)
        harnesses.append(harness)
        return harness

    yield make
    for harness in harnesses:
        harness.pool.shutdown()


def test_stale_thread_item_neither_runs_nor_completes_the_newer_execution(make_harness):
    harness = make_harness("thread")
    harness.submit()
    fresh_generation = harness.abort_and_replace()

    harness.run_next_item()

    assert harness.thread_runs == []
    assert harness.node_outcome() == ("running", None)
    assert harness.ignored == [("pool_item_dropped", "stale_execution")]
    assert len(harness.finished_items) == 1

    harness.run_next_item()

    assert harness.thread_runs == [fresh_generation]
    assert harness.node_outcome() == ("complete", {"generation": fresh_generation})
    assert len(harness.finished_items) == 2


def test_stale_remote_item_is_not_submitted_to_its_executor(make_harness):
    harness = make_harness("interpreter")
    harness.submit()
    fresh_generation = harness.abort_and_replace()

    harness.run_next_item()

    assert harness.remote_executor.submitted == []
    assert harness.node_outcome() == ("running", None)
    assert harness.ignored == [("pool_item_dropped", "stale_execution")]
    assert len(harness.finished_items) == 1

    harness.run_next_item()
    harness.remote_executor.finish(0)

    assert harness.node_outcome() == ("complete", {"generation": fresh_generation})
    assert harness.pool.snapshot_remote_futures() == ()


def test_stale_remote_future_finishing_late_does_not_complete_the_newer_execution(make_harness):
    harness = make_harness("interpreter")
    stale_generation = harness.submit()
    harness.run_next_item()
    fresh_generation = harness.abort_and_replace()

    harness.remote_executor.finish(0)

    assert harness.remote_executor.submitted[0][0] == {"generation": stale_generation}
    assert harness.node_outcome() == ("running", None)
    assert harness.ignored == [("pool_finish_ignored", "stale_execution")]
    assert len(harness.finished_items) == 1

    harness.run_next_item()
    harness.remote_executor.finish(1)

    assert harness.node_outcome() == ("complete", {"generation": fresh_generation})
    assert harness.pool.snapshot_remote_futures() == ()
