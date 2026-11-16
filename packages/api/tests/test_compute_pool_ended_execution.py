"""A holding dequeue predicate never holds a pool item whose execution has ended.

Compute-diagnostics freeze holds queued work through the pool's dequeue
predicate. An item whose execution was aborted or replaced while it waited is
not live work: the pool picks it whatever the predicate says, and the
orchestrator drops it unrun. A live item stays held.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.compute import ComputeRequest
from api.compute.errors import ComputeScopeAbortedError

from tests.compute_lifecycle_records import kinds_and_reasons
from tests.stale_pool_item_helpers import StaleItemHarness


@pytest.fixture
def harness(sample_turn) -> Iterator[StaleItemHarness]:
    """One thread-backed scope on a worker-less pool, with its ignore records."""
    harness = StaleItemHarness(sample_turn, "thread")
    yield harness
    harness.pool.shutdown()


def _hold_everything(harness: StaleItemHarness) -> None:
    """Set a predicate that holds every item, as freeze does for in-scope work."""
    harness.pool.set_dequeue_predicate(lambda _item: False)


def test_a_live_item_stays_held(harness):
    harness.submit()
    _hold_everything(harness)

    assert harness.pool.take_next_item_for_tests() is None
    assert len(harness.pool.snapshot_work_queue()) == 1


def test_an_aborted_execution_item_is_picked_and_dropped(harness):
    harness.submit()
    _hold_everything(harness)
    assert harness.orchestrator.abort_scope(harness.scope, ComputeScopeAbortedError("cancelled"))

    harness.run_next_item()

    assert harness.thread_runs == []
    assert kinds_and_reasons(harness.ignored) == [("pool_item_dropped", "node_not_running")]
    assert harness.pool.snapshot_work_queue() == ()


def test_a_replaced_execution_item_is_dropped_and_the_newer_one_stays_held(harness):
    harness.submit()
    _hold_everything(harness)
    fresh_generation = harness.abort_and_replace()

    harness.run_next_item()

    assert harness.thread_runs == []
    assert kinds_and_reasons(harness.ignored) == [("pool_item_dropped", "stale_execution")]
    (held,) = harness.pool.snapshot_work_queue()
    assert held.item.execution_generation == fresh_generation
    assert harness.pool.take_next_item_for_tests() is None


def test_published_execution_follows_the_node_through_abort_and_replace(harness):
    first_generation = harness.submit()
    published = harness.orchestrator.published_execution(harness.scope)
    assert published is not None
    assert published.execution_generation == first_generation

    assert harness.orchestrator.abort_scope(harness.scope, ComputeScopeAbortedError("cancelled"))
    assert harness.orchestrator.published_execution(harness.scope) is None

    fresh_generation = harness.submit(force_fresh=True)
    published = harness.orchestrator.published_execution(harness.scope)
    assert published is not None
    assert published.execution_generation == fresh_generation != first_generation


def test_an_ended_item_ranks_background_not_at_the_newer_executions_band(harness):
    harness.submit()
    assert harness.orchestrator.abort_scope(harness.scope, ComputeScopeAbortedError("cancelled"))
    harness.orchestrator.submit(
        ComputeRequest(
            ctx=harness.ctx,
            scope=harness.scope,
            force_fresh=True,
            priority_band="interactive_ensure",
        )
    )

    stale, fresh = harness.pool.snapshot_work_queue()

    assert stale.item.execution_generation != fresh.item.execution_generation
    assert (stale.priority_band, fresh.priority_band) == ("background", "interactive_ensure")


def test_an_ended_item_is_picked_ahead_of_higher_band_live_work(harness):
    harness.submit()
    assert harness.orchestrator.abort_scope(harness.scope, ComputeScopeAbortedError("cancelled"))
    harness.orchestrator.submit(
        ComputeRequest(
            ctx=harness.ctx,
            scope=harness.scope,
            force_fresh=True,
            priority_band="interactive_ensure",
        )
    )

    picked = harness.pool.take_next_item_for_tests()

    assert picked is not None and picked.priority_band == "background"
    assert harness.orchestrator.published_execution(harness.scope).execution_generation != (
        picked.item.execution_generation
    )
