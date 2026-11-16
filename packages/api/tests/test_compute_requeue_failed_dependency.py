"""A node that re-enters dispatch settles on a dependency that failed while it ran.

A running or parked node takes no dependency-terminal refresh, so a
dependency that fails meanwhile is seen only when the node re-enters
dispatch. These tests drive pool steps by hand and never call
``run_until_idle``, whose readiness refresh over every node would hide a node
left waiting with no wake.

Dependency edges come from the diamond export fixture: ROOT ensures BRANCH_B
and BRANCH_C, and each branch ensures SHARED.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from api.analytics.export_context import AnalyticQueryContext
from api.compute import (
    ComputeHandle,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    build_compute_registry,
)
from api.compute.errors import ComputeScopeAbortedError
from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery
from api.compute.wire import StepResult

from tests.compute_orchestrator_fixtures import (
    RecordingPersistencePolicy,
    inline_compute_registration,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import (
    BRANCH_B_ID,
    BRANCH_C_ID,
    ROOT_ID,
    SHARED_ID,
)
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)


class DeferringPersistencePolicy(RecordingPersistencePolicy):
    """Records persists, or raises ``PersistDeferredError`` with ``recovery`` once set."""

    def __init__(self) -> None:
        super().__init__()
        self.recovery: PersistDependencyRecovery | None = None

    def persist(self, ctx, scope, result_wire) -> None:
        if self.recovery is not None:
            raise PersistDeferredError("dependency must re-close", recovery=self.recovery)
        super().persist(ctx, scope, result_wire)


@dataclass(frozen=True)
class RunningBranch:
    """BRANCH_B running on a complete SHARED, with ROOT waiting on it."""

    orchestrator: ComputeOrchestrator
    ctx: AnalyticQueryContext
    shared: ComputeScope
    branch: ComputeScope
    root: ComputeScope
    branch_policy: DeferringPersistencePolicy
    branch_waiter: ComputeHandle


def _hold_pool_steps(node, step, **_kwargs) -> None:
    del node, step


def _running_branch(sample_turn) -> RunningBranch:
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    export_scope = make_export_scope(sample_turn)
    branch_policy = DeferringPersistencePolicy()
    registry = build_compute_registry(
        (
            pool_compute_registration(
                SHARED_ID, backend="thread", persistence_policy=RecordingPersistencePolicy()
            ),
            pool_compute_registration(
                BRANCH_B_ID, backend="thread", persistence_policy=branch_policy
            ),
            inline_compute_registration(BRANCH_C_ID),
            pool_compute_registration(
                ROOT_ID, backend="thread", persistence_policy=RecordingPersistencePolicy()
            ),
        )
    )
    orchestrator = ComputeOrchestrator(compute_registry=registry, pool_submitter=_hold_pool_steps)
    shared = make_compute_scope(SHARED_ID, export_scope)
    branch = make_compute_scope(BRANCH_B_ID, export_scope)
    root = make_compute_scope(ROOT_ID, export_scope)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root))
    complete_running_pool_step(orchestrator, shared, result_wire={"result": SHARED_ID})
    assert orchestrator.nodes[branch].state == "running"
    assert orchestrator.nodes[root].state == "waiting_deps"
    branch_waiter = orchestrator.submit(ComputeRequest(ctx=ctx, scope=branch))
    assert branch_waiter.is_waiter

    return RunningBranch(
        orchestrator=orchestrator,
        ctx=ctx,
        shared=shared,
        branch=branch,
        root=root,
        branch_policy=branch_policy,
        branch_waiter=branch_waiter,
    )


def _replace_shared_under_running_branch(setup: RunningBranch) -> None:
    """Replace complete SHARED with a fresh execution while BRANCH_B runs."""
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.shared, force_fresh=True))
    assert setup.orchestrator.nodes[setup.shared].state == "running"
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def _fail_shared_while_branch_runs(setup: RunningBranch, error: BaseException) -> None:
    _replace_shared_under_running_branch(setup)
    complete_running_pool_step(setup.orchestrator, setup.shared, error=error)
    assert setup.orchestrator.nodes[setup.shared].state == "failed"
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def _abort_shared_while_branch_runs(setup: RunningBranch) -> None:
    _replace_shared_under_running_branch(setup)
    assert setup.orchestrator.abort_scope(
        setup.shared, ComputeScopeAbortedError("discarded by a bump")
    )
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def _finish_branch_step_epoch_stale(setup: RunningBranch) -> None:
    setup.branch_policy.invalidate(setup.ctx, setup.branch)
    complete_running_pool_step(setup.orchestrator, setup.branch, result_wire={"result": "stale"})


def test_epoch_retry_cascades_a_dependency_that_failed_while_the_node_ran(sample_turn):
    setup = _running_branch(sample_turn)
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)

    _finish_branch_step_epoch_stale(setup)

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure
    assert setup.branch_waiter.error is shared_failure
    assert setup.orchestrator.nodes[setup.root].state == "failed"


def test_epoch_retry_leaves_the_node_waiting_on_an_aborted_dependency(sample_turn):
    setup = _running_branch(sample_turn)
    _abort_shared_while_branch_runs(setup)
    aborted_shared = setup.orchestrator.nodes[setup.shared]

    _finish_branch_step_epoch_stale(setup)

    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.branch, force_fresh=True))
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not aborted_shared
    assert recreated_shared.state == "running"


def test_continue_cascades_a_dependency_that_failed_while_the_node_ran(sample_turn):
    setup = _running_branch(sample_turn)
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)

    complete_running_pool_step(
        setup.orchestrator, setup.branch, result_wire=StepResult(outcome="continue")
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure


def test_parked_wake_cascades_a_dependency_that_failed_while_the_node_ran(sample_turn):
    setup = _running_branch(sample_turn)
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)
    complete_running_pool_step(
        setup.orchestrator,
        setup.branch,
        result_wire=StepResult(outcome="park", park_reason="test_park"),
    )
    assert setup.orchestrator.nodes[setup.branch].state == "parked"

    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.branch, force_fresh=True))

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure


def test_resolving_readiness_of_a_terminal_node_is_refused(sample_turn):
    setup = _running_branch(sample_turn)
    shared_node = setup.orchestrator.nodes[setup.shared]
    assert shared_node.state == "complete"

    with setup.orchestrator._condition, pytest.raises(RuntimeError, match="terminal"):
        setup.orchestrator._resolve_readiness(shared_node)


def _other_player_shared_scope(setup: RunningBranch, sample_turn) -> ComputeScope:
    """SHARED for a second player; BRANCH_B has no edge to it."""
    other_shared = replace(setup.shared, player_id=sample_turn.scores[1].ownerid)
    assert other_shared != setup.shared
    return other_shared


def _complete_other_player_shared(setup: RunningBranch, sample_turn) -> ComputeScope:
    """Run the second player's SHARED to completion."""
    other_shared = _other_player_shared_scope(setup, sample_turn)
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=other_shared))
    complete_running_pool_step(setup.orchestrator, other_shared, result_wire={"result": "other"})
    assert setup.orchestrator.nodes[other_shared].state == "complete"
    return other_shared


def _persist_deferred_scopes(orchestrator: ComputeOrchestrator) -> list[ComputeScope]:
    """The scope of each ``persist_deferred`` lifecycle record from now on."""
    scopes: list[ComputeScope] = []

    def record(kind, scope, _node, _generation, _step_kind, _step_index, _detail) -> None:
        if kind == "persist_deferred":
            scopes.append(scope)

    orchestrator.observers.register_lifecycle_listener(record)
    return scopes


def _persist_branch_step_deferred(
    setup: RunningBranch, recovery: PersistDependencyRecovery
) -> None:
    setup.branch_policy.recovery = recovery
    complete_running_pool_step(
        setup.orchestrator,
        setup.branch,
        result_wire=StepResult(outcome="persist", payload={"result": BRANCH_B_ID}),
    )


def test_soft_defer_cascades_a_dependency_that_failed_while_the_node_ran(sample_turn):
    setup = _running_branch(sample_turn)
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)

    complete_running_pool_step(
        setup.orchestrator, setup.branch, result_wire=StepResult(outcome="waiting_deps")
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure


def test_persist_deferred_cascades_a_failed_dependency_it_is_not_recreating(sample_turn):
    """Only the recovery dependency is excluded; another failed dependency still cascades."""
    setup = _running_branch(sample_turn)
    other_shared = _complete_other_player_shared(setup, sample_turn)
    other_shared_node = setup.orchestrator.nodes[other_shared]
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)
    persist_deferred_scopes = _persist_deferred_scopes(setup.orchestrator)

    _persist_branch_step_deferred(
        setup,
        PersistDependencyRecovery(
            dependency_scope=other_shared, force_fresh=True, step_kind="materialize"
        ),
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure
    assert setup.orchestrator.nodes[other_shared] is other_shared_node
    assert other_shared_node.state == "complete"
    assert persist_deferred_scopes == []


def test_persist_deferred_recreates_a_failed_recovery_dependency(sample_turn):
    setup = _running_branch(sample_turn)
    _fail_shared_while_branch_runs(setup, RuntimeError("shared replacement failed"))
    failed_shared = setup.orchestrator.nodes[setup.shared]
    persist_deferred_scopes = _persist_deferred_scopes(setup.orchestrator)

    _persist_branch_step_deferred(
        setup,
        PersistDependencyRecovery(
            dependency_scope=setup.shared, force_fresh=True, step_kind="materialize"
        ),
    )

    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    assert persist_deferred_scopes == [setup.branch]
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not failed_shared
    assert recreated_shared.state == "running"


def test_persist_deferred_cascades_a_failed_recovery_dependency_it_grafts(sample_turn):
    """Without force_fresh, a failed recovery dependency outside the node's edges cascades."""
    setup = _running_branch(sample_turn)
    other_shared = _other_player_shared_scope(setup, sample_turn)
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=other_shared))
    other_failure = RuntimeError("other shared failed")
    complete_running_pool_step(setup.orchestrator, other_shared, error=other_failure)
    assert other_shared not in setup.orchestrator.nodes[setup.branch].dependency_scopes

    _persist_branch_step_deferred(
        setup,
        PersistDependencyRecovery(
            dependency_scope=other_shared, force_fresh=False, step_kind="materialize"
        ),
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is other_failure
