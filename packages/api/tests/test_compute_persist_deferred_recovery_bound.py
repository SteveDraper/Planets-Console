"""A persist-deferred recovery that changed nothing is not retried.

When a node defers a second time onto the same dependency, at the same
invalidation generation, after that dependency's recreation completed, it fails
with ``PersistDependencyRecoveryExhaustedError`` instead of recreating the
dependency again. A moved generation is a new reason to wait, so the node
recovers again.

The key is the deferring node's own generation, so two gaps are accepted:
recreations that move it every round are not bounded, and a dependency reopened
without moving it fails a re-deferral that had a real cause. Both are pinned
here in their generic form.
"""

from __future__ import annotations

from api.compute import ComputeRequest
from api.compute.errors import ComputeScopeAbortedError, PersistDependencyRecoveryExhaustedError

from tests.compute_lifecycle_records import record_lifecycle
from tests.compute_persist_deferred_helpers import (
    RunningBranch,
    persist_branch_step_deferred,
    running_branch,
    shared_recovery,
)
from tests.compute_pool_test_helpers import complete_running_pool_step


def _complete_the_recreated_shared(setup: RunningBranch) -> None:
    """Finish the recreated SHARED; BRANCH_B is then dispatched again."""
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": "shared"})
    assert setup.orchestrator.nodes[setup.shared].state == "complete"
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def _assert_exhausted(setup: RunningBranch) -> None:
    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert isinstance(branch_node.error, PersistDependencyRecoveryExhaustedError)
    assert branch_node.error.recovery_scope == setup.shared
    assert setup.branch_waiter.error is branch_node.error


def _assert_recovering(setup: RunningBranch) -> None:
    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    assert setup.orchestrator.nodes[setup.shared].state == "running"


def test_a_second_deferral_at_the_same_generation_fails_after_one_retry(sample_turn):
    """Also the pin for a dependency reopened without moving the key (accepted gap)."""
    setup = running_branch(sample_turn)
    recovery = shared_recovery(setup)
    persist_branch_step_deferred(setup, recovery)
    _assert_recovering(setup)
    _complete_the_recreated_shared(setup)
    shared_after_retry = setup.orchestrator.nodes[setup.shared]
    events = record_lifecycle(
        setup.orchestrator, ("persist_deferred", "persist_recovery_exhausted")
    )

    persist_branch_step_deferred(setup, recovery)

    _assert_exhausted(setup)
    assert setup.orchestrator.nodes[setup.shared] is shared_after_retry
    assert [event.kind for event in events] == ["persist_recovery_exhausted"]
    (exhausted,) = events
    assert exhausted.scope == setup.branch


def test_a_moved_generation_lets_the_node_recover_again(sample_turn):
    """Also the pin for recreations that move the key every round (accepted gap)."""
    setup = running_branch(sample_turn)
    recovery = shared_recovery(setup)
    persist_branch_step_deferred(setup, recovery)
    setup.branch_policy.invalidate(setup.ctx, setup.branch)
    _complete_the_recreated_shared(setup)

    persist_branch_step_deferred(setup, recovery)

    _assert_recovering(setup)
    deferral = setup.orchestrator.nodes[setup.branch].last_persist_deferral
    assert deferral is not None
    assert deferral.invalidation_generation == setup.branch_policy.generation


def test_a_recovery_onto_a_live_dependency_counts_as_the_one_retry(sample_turn):
    setup = running_branch(sample_turn)
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.shared, force_fresh=True))
    recovery = shared_recovery(setup)
    persist_branch_step_deferred(setup, recovery)
    _assert_recovering(setup)
    assert setup.orchestrator.nodes[setup.branch].superseded_dependency is None
    _complete_the_recreated_shared(setup)

    persist_branch_step_deferred(setup, recovery)

    _assert_exhausted(setup)


def test_an_aborted_recreation_recreated_by_the_attach_walk_fails_only_once(sample_turn):
    setup = running_branch(sample_turn)
    recovery = shared_recovery(setup)
    persist_branch_step_deferred(setup, recovery)
    assert setup.orchestrator.abort_scope(
        setup.shared, ComputeScopeAbortedError("discarded by a bump")
    )
    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.branch, force_fresh=True))
    assert setup.orchestrator.nodes[setup.shared].state == "running"
    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    _complete_the_recreated_shared(setup)

    persist_branch_step_deferred(setup, recovery)

    _assert_exhausted(setup)


def test_an_epoch_retry_between_two_deferrals_moves_the_key(sample_turn):
    setup = running_branch(sample_turn)
    recovery = shared_recovery(setup)
    persist_branch_step_deferred(setup, recovery)
    _complete_the_recreated_shared(setup)
    setup.branch_policy.invalidate(setup.ctx, setup.branch)
    complete_running_pool_step(setup.orchestrator, setup.branch, result_wire={"result": "stale"})
    assert setup.orchestrator.nodes[setup.branch].state == "running"

    persist_branch_step_deferred(setup, recovery)

    _assert_recovering(setup)
