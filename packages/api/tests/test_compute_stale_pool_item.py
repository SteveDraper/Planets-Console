"""A pool item is bound to the execution of its scope that dispatched it.

A node aborted while its pool item waits, then replaced by a ``force_fresh``
submit, runs as a newer execution of the same scope. The older execution's
item must neither run its step nor complete the newer node, on the thread
path and on the remote-future path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from api.compute.profile import ComputeBackend

from tests.compute_lifecycle_records import kinds_and_reasons
from tests.stale_pool_item_helpers import (
    StaleItemHarness,
)


@pytest.fixture
def make_harness(sample_turn) -> Iterator[Callable[[ComputeBackend], StaleItemHarness]]:
    harnesses: list[StaleItemHarness] = []

    def make(backend: ComputeBackend) -> StaleItemHarness:
        harness = StaleItemHarness(sample_turn, backend)
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
    assert kinds_and_reasons(harness.ignored) == [("pool_item_dropped", "stale_execution")]
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
    assert kinds_and_reasons(harness.ignored) == [("pool_item_dropped", "stale_execution")]
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
    assert kinds_and_reasons(harness.ignored) == [("pool_finish_ignored", "stale_execution")]
    assert len(harness.finished_items) == 1

    harness.run_next_item()
    harness.remote_executor.finish(1)

    assert harness.node_outcome() == ("complete", {"generation": fresh_generation})
    assert harness.pool.snapshot_remote_futures() == ()
