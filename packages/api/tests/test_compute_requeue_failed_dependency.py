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
from api.analytics.registration import (
    TurnAnalyticRegistration,
    resolve_registration_export_catalog,
)
from api.compute import (
    ComputeHandle,
    ComputeNodeRun,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    build_compute_registry,
)
from api.compute.errors import ComputeScopeAbortedError
from api.compute.persistence import (
    InvalidPersistDependencyRecoveryError,
    PersistDeferredError,
    PersistDependencyRecovery,
)
from api.compute.scope import format_compute_scope_key
from api.compute.wire import StepResult

from tests.compute_lifecycle_records import record_lifecycle
from tests.compute_orchestrator_fixtures import (
    ArmableRootPlanHook,
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
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE


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
    """BRANCH_B running on a complete SHARED, with ROOT waiting on it.

    ``shared_root_plan`` is SHARED's root plan hook; arm it to act inside the
    next SHARED-rooted submission.
    """

    orchestrator: ComputeOrchestrator
    ctx: AnalyticQueryContext
    shared: ComputeScope
    branch: ComputeScope
    root: ComputeScope
    branch_policy: DeferringPersistencePolicy
    branch_waiter: ComputeHandle
    shared_root_plan: ArmableRootPlanHook


def _hold_pool_steps(node, step, **_kwargs) -> None:
    del node, step


def _running_branch(
    sample_turn, *, extra_registrations: tuple[TurnAnalyticRegistration, ...] = ()
) -> RunningBranch:
    """Set up the diamond, plus ``extra_registrations`` in both registries."""
    export_registry = {
        **DIAMOND_FIXTURE_EXPORT_REGISTRY,
        **{
            registration.catalog_entry.id: resolve_registration_export_catalog(registration)
            for registration in extra_registrations
        },
    }
    ctx = make_fixture_query_context(sample_turn, registry=export_registry)
    export_scope = make_export_scope(sample_turn)
    branch_policy = DeferringPersistencePolicy()
    shared_root_plan = ArmableRootPlanHook()
    registry = build_compute_registry(
        (
            replace(
                pool_compute_registration(
                    SHARED_ID, backend="thread", persistence_policy=RecordingPersistencePolicy()
                ),
                open_root_plan=shared_root_plan,
            ),
            pool_compute_registration(
                BRANCH_B_ID, backend="thread", persistence_policy=branch_policy
            ),
            inline_compute_registration(BRANCH_C_ID),
            pool_compute_registration(
                ROOT_ID, backend="thread", persistence_policy=RecordingPersistencePolicy()
            ),
            *extra_registrations,
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
        shared_root_plan=shared_root_plan,
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
    """Only the recovery dependency is superseded; another failed dependency still cascades."""
    setup = _running_branch(sample_turn)
    other_shared = _complete_other_player_shared(setup, sample_turn)
    other_shared_node = setup.orchestrator.nodes[other_shared]
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)
    persist_deferred = record_lifecycle(setup.orchestrator, ("persist_deferred",))

    _persist_branch_step_deferred(
        setup,
        PersistDependencyRecovery(dependency_scope=other_shared, step_kind="materialize"),
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure
    assert setup.orchestrator.nodes[other_shared] is other_shared_node
    assert other_shared_node.state == "complete"
    assert persist_deferred == []


def test_persist_deferred_recreates_a_failed_recovery_dependency(sample_turn):
    setup = _running_branch(sample_turn)
    _fail_shared_while_branch_runs(setup, RuntimeError("shared replacement failed"))
    failed_shared = setup.orchestrator.nodes[setup.shared]
    persist_deferred = record_lifecycle(setup.orchestrator, ("persist_deferred",))

    _persist_branch_step_deferred(
        setup,
        PersistDependencyRecovery(dependency_scope=setup.shared, step_kind="materialize"),
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "waiting_deps"
    assert [(record.scope, record.detail) for record in persist_deferred] == [
        (
            setup.branch,
            {
                "reason": "persist_deferred",
                "priorProfileStepIndex": branch_node.profile_step_index,
                "relatedScopeKey": format_compute_scope_key(setup.shared),
                "dependencyStepKind": "materialize",
                "priorityBand": branch_node.priority_band,
                "supersededExecutionGeneration": failed_shared.execution_generation,
            },
        )
    ]
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not failed_shared
    assert recreated_shared.state == "running"


def test_persist_deferred_recreates_a_failed_recovery_dependency_it_grafts(sample_turn):
    """A failed recovery dependency outside the node's edges is grafted and recreated."""
    setup = _running_branch(sample_turn)
    other_shared = _other_player_shared_scope(setup, sample_turn)
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=other_shared))
    complete_running_pool_step(
        setup.orchestrator, other_shared, error=RuntimeError("other shared failed")
    )
    failed_other_shared = setup.orchestrator.nodes[other_shared]
    assert other_shared not in setup.orchestrator.nodes[setup.branch].dependency_scopes

    _persist_branch_step_deferred(
        setup, PersistDependencyRecovery(dependency_scope=other_shared, step_kind="materialize")
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "waiting_deps"
    assert other_shared in branch_node.dependency_scopes
    recreated_other_shared = setup.orchestrator.nodes[other_shared]
    assert recreated_other_shared is not failed_other_shared
    assert recreated_other_shared.state == "running"


# An inline fixture analytic; its registration's export catalog is empty.
UNCATALOGED_ID = "export-test-uncataloged"


def _assert_branch_fails_without_recovery(
    setup: RunningBranch, recovery: PersistDependencyRecovery
) -> None:
    """The deferral fails BRANCH_B at demotion: no record, no dependency node change."""
    nodes_before = dict(setup.orchestrator.nodes)
    persist_deferred = record_lifecycle(setup.orchestrator, ("persist_deferred",))

    _persist_branch_step_deferred(setup, recovery)

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert isinstance(branch_node.error, InvalidPersistDependencyRecoveryError)
    assert branch_node.error.recovery == recovery
    assert setup.branch_waiter.error is branch_node.error
    assert setup.orchestrator.nodes.get(recovery.dependency_scope) is nodes_before.get(
        recovery.dependency_scope
    )
    assert persist_deferred == []


def test_persist_deferred_fails_a_recovery_naming_an_unknown_step_kind(sample_turn):
    setup = _running_branch(sample_turn)
    shared_node = setup.orchestrator.nodes[setup.shared]

    _assert_branch_fails_without_recovery(
        setup, PersistDependencyRecovery(dependency_scope=setup.shared, step_kind="tier_solve")
    )

    assert shared_node.state == "complete"


def test_persist_deferred_fails_a_recovery_of_an_analytic_with_no_export_catalog(sample_turn):
    setup = _running_branch(
        sample_turn, extra_registrations=(inline_compute_registration(UNCATALOGED_ID),)
    )
    uncataloged = replace(setup.shared, analytic_id=UNCATALOGED_ID)

    _assert_branch_fails_without_recovery(
        setup, PersistDependencyRecovery(dependency_scope=uncataloged, step_kind="materialize")
    )


def _defer_branch_step_by_wait_recovery(
    setup: RunningBranch, recovery: PersistDependencyRecovery
) -> None:
    complete_running_pool_step(
        setup.orchestrator,
        setup.branch,
        result_wire=StepResult(outcome="waiting_deps", wait_recovery=recovery),
    )


# The two ways a step asks for a dependency recovery.
_RECOVERY_DEFERRALS = {
    "persist-deferred": _persist_branch_step_deferred,
    "wait-recovery": _defer_branch_step_by_wait_recovery,
}


def _shared_recovery(setup: RunningBranch) -> PersistDependencyRecovery:
    return PersistDependencyRecovery(dependency_scope=setup.shared, step_kind="materialize")


def _arm_unrelated_submit_before_the_recreate(setup: RunningBranch, sample_turn) -> ComputeScope:
    """Submit the second player's SHARED as the recovery's SHARED submit opens.

    That fresh plan refreshes readiness across the DAG after BRANCH_B's
    demotion and before the recreated SHARED registers.
    """
    other_shared = _other_player_shared_scope(setup, sample_turn)

    def submit_other_shared() -> None:
        setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=other_shared))

    setup.shared_root_plan.arm(on_enter=submit_other_shared)
    return other_shared


def _assert_branch_waits_on_a_recreated_shared(
    setup: RunningBranch, superseded_shared: ComputeNodeRun, other_shared: ComputeScope
) -> None:
    """The window submit ran, and BRANCH_B waits on a running recreation of SHARED."""
    assert setup.orchestrator.nodes[other_shared].state == "running"
    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "waiting_deps"
    assert branch_node.superseded_dependency == superseded_shared.execution_ref
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not superseded_shared
    assert recreated_shared.state == "running"


@pytest.mark.parametrize("defer", _RECOVERY_DEFERRALS.values(), ids=_RECOVERY_DEFERRALS.keys())
def test_a_refresh_before_the_recreate_registers_does_not_cascade_the_superseded_failure(
    sample_turn, defer
):
    setup = _running_branch(sample_turn)
    _fail_shared_while_branch_runs(setup, RuntimeError("superseded shared failed"))
    failed_shared = setup.orchestrator.nodes[setup.shared]
    other_shared = _arm_unrelated_submit_before_the_recreate(setup, sample_turn)

    defer(setup, _shared_recovery(setup))

    _assert_branch_waits_on_a_recreated_shared(setup, failed_shared, other_shared)
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": SHARED_ID})
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def test_a_failed_recreate_cascades_its_own_error_not_the_superseded_one(sample_turn):
    setup = _running_branch(sample_turn)
    _fail_shared_while_branch_runs(setup, RuntimeError("superseded shared failed"))
    _arm_unrelated_submit_before_the_recreate(setup, sample_turn)
    _persist_branch_step_deferred(setup, _shared_recovery(setup))
    recreate_failure = RuntimeError("recreated shared failed")

    complete_running_pool_step(setup.orchestrator, setup.shared, error=recreate_failure)

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is recreate_failure


def test_a_refresh_before_the_recreate_registers_does_not_promote_on_the_superseded_complete(
    sample_turn,
):
    """A complete SHARED already persisted is re-run, and BRANCH_B waits for that run."""
    setup = _running_branch(sample_turn)
    complete_shared = setup.orchestrator.nodes[setup.shared]
    assert complete_shared.state == "complete"
    FIXTURE_EXPORT_STATE.mark_persisted(SHARED_ID, make_export_scope(sample_turn))
    other_shared = _arm_unrelated_submit_before_the_recreate(setup, sample_turn)

    _persist_branch_step_deferred(setup, _shared_recovery(setup))

    _assert_branch_waits_on_a_recreated_shared(setup, complete_shared, other_shared)
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": SHARED_ID})
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def test_a_recovery_of_a_running_dependency_waits_on_that_execution(sample_turn):
    setup = _running_branch(sample_turn)
    _replace_shared_under_running_branch(setup)
    running_shared = setup.orchestrator.nodes[setup.shared]
    persist_deferred = record_lifecycle(setup.orchestrator, ("persist_deferred",))

    _persist_branch_step_deferred(setup, _shared_recovery(setup))

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "waiting_deps"
    assert branch_node.superseded_dependency is None
    assert [record.detail["supersededExecutionGeneration"] for record in persist_deferred] == [None]
    assert setup.orchestrator.nodes[setup.shared] is running_shared
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": SHARED_ID})
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def test_a_force_fresh_attach_before_the_recreate_does_not_recreate_the_superseded_abort(
    sample_turn,
):
    """The recreate-aborted walk leaves the superseded SHARED to the recovery submit."""
    setup = _running_branch(sample_turn)
    _abort_shared_while_branch_runs(setup)
    aborted_shared = setup.orchestrator.nodes[setup.shared]

    def attach_branch_force_fresh() -> None:
        setup.orchestrator.submit(
            ComputeRequest(ctx=setup.ctx, scope=setup.branch, force_fresh=True)
        )

    setup.shared_root_plan.arm(on_enter=attach_branch_force_fresh)
    force_fresh_submits = record_lifecycle(
        setup.orchestrator, ("force_fresh_replace", "force_fresh_attach")
    )

    _persist_branch_step_deferred(setup, _shared_recovery(setup))

    assert [record.kind for record in force_fresh_submits if record.scope == setup.shared] == [
        "force_fresh_replace"
    ]
    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not aborted_shared
    assert recreated_shared.state == "running"
