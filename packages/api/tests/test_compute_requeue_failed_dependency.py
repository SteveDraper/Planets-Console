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

import logging
import threading
from dataclasses import dataclass, replace

import pytest
from api.compute import (
    ComputeNodeRun,
    ComputeRequest,
    ComputeScope,
)
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator_state import PersistDeferral
from api.compute.persistence import (
    InvalidPersistDependencyRecoveryError,
    PersistDependencyRecovery,
)
from api.compute.scope import format_compute_scope_key
from api.compute.wire import StepResult

from tests.compute_lifecycle_records import record_lifecycle
from tests.compute_orchestrator_fixtures import (
    inline_compute_registration,
    make_export_scope,
)
from tests.compute_persist_deferred_helpers import (
    RunningBranch,
    branch_superseded_execution,
    persist_branch_step_deferred,
    running_branch,
    shared_recovery,
)
from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.contained_callback_guard import CONTAINMENT_LOGGER
from tests.fixtures.export_framework.diamond_exports import (
    SHARED_ID,
)
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE


def _replace_shared_underrunning_branch(setup: RunningBranch) -> None:
    """Replace complete SHARED with a fresh execution while BRANCH_B runs."""
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.shared, force_fresh=True))
    assert setup.orchestrator.nodes[setup.shared].state == "running"
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def _fail_shared_while_branch_runs(setup: RunningBranch, error: BaseException) -> None:
    _replace_shared_underrunning_branch(setup)
    complete_running_pool_step(setup.orchestrator, setup.shared, error=error)
    assert setup.orchestrator.nodes[setup.shared].state == "failed"
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def _abort_shared_while_branch_runs(setup: RunningBranch) -> None:
    _replace_shared_underrunning_branch(setup)
    assert setup.orchestrator.abort_scope(
        setup.shared, ComputeScopeAbortedError("discarded by a bump")
    )
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def _finish_branch_step_epoch_stale(setup: RunningBranch) -> None:
    setup.branch_policy.invalidate(setup.ctx, setup.branch)
    complete_running_pool_step(setup.orchestrator, setup.branch, result_wire={"result": "stale"})


def test_epoch_retry_cascades_a_dependency_that_failed_while_the_node_ran(sample_turn):
    setup = running_branch(sample_turn)
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)

    _finish_branch_step_epoch_stale(setup)

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure
    assert setup.branch_waiter.error is shared_failure
    assert setup.orchestrator.nodes[setup.root].state == "failed"


def test_epoch_retry_leaves_the_node_waiting_on_an_aborted_dependency(sample_turn):
    setup = running_branch(sample_turn)
    _abort_shared_while_branch_runs(setup)
    aborted_shared = setup.orchestrator.nodes[setup.shared]

    _finish_branch_step_epoch_stale(setup)

    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.branch, force_fresh=True))
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not aborted_shared
    assert recreated_shared.state == "running"


def test_continue_cascades_a_dependency_that_failed_while_the_node_ran(sample_turn):
    setup = running_branch(sample_turn)
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)

    complete_running_pool_step(
        setup.orchestrator, setup.branch, result_wire=StepResult(outcome="continue")
    )

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is shared_failure


def test_parked_wake_cascades_a_dependency_that_failed_while_the_node_ran(sample_turn):
    setup = running_branch(sample_turn)
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
    setup = running_branch(sample_turn)
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


def test_persist_deferred_cascades_a_failed_dependency_it_is_not_recreating(sample_turn):
    """Only the recovery dependency is superseded; another failed dependency still cascades."""
    setup = running_branch(sample_turn)
    other_shared = _complete_other_player_shared(setup, sample_turn)
    other_shared_node = setup.orchestrator.nodes[other_shared]
    shared_failure = RuntimeError("shared replacement failed")
    _fail_shared_while_branch_runs(setup, shared_failure)
    persist_deferred = record_lifecycle(setup.orchestrator, ("persist_deferred",))

    persist_branch_step_deferred(
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
    setup = running_branch(sample_turn)
    _fail_shared_while_branch_runs(setup, RuntimeError("shared replacement failed"))
    failed_shared = setup.orchestrator.nodes[setup.shared]
    persist_deferred = record_lifecycle(setup.orchestrator, ("persist_deferred",))

    persist_branch_step_deferred(
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
    setup = running_branch(sample_turn)
    other_shared = _other_player_shared_scope(setup, sample_turn)
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=other_shared))
    complete_running_pool_step(
        setup.orchestrator, other_shared, error=RuntimeError("other shared failed")
    )
    failed_other_shared = setup.orchestrator.nodes[other_shared]
    assert other_shared not in setup.orchestrator.nodes[setup.branch].dependency_scopes

    persist_branch_step_deferred(
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

    persist_branch_step_deferred(setup, recovery)

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
    setup = running_branch(sample_turn)
    shared_node = setup.orchestrator.nodes[setup.shared]

    _assert_branch_fails_without_recovery(
        setup, PersistDependencyRecovery(dependency_scope=setup.shared, step_kind="tier_solve")
    )

    assert shared_node.state == "complete"


def test_persist_deferred_fails_a_recovery_of_an_analytic_with_no_export_catalog(sample_turn):
    setup = running_branch(
        sample_turn, extra_registrations=(inline_compute_registration(UNCATALOGED_ID),)
    )
    uncataloged = replace(setup.shared, analytic_id=UNCATALOGED_ID)

    _assert_branch_fails_without_recovery(
        setup, PersistDependencyRecovery(dependency_scope=uncataloged, step_kind="materialize")
    )


def _submit_from_another_thread(setup: RunningBranch, request: ComputeRequest) -> None:
    """Submit ``request`` on a second thread and wait for it, re-raising its failure.

    A submit that lands while the recovery's root plan is open comes from
    another thread: the filling thread cannot submit inside its own root plan.
    """
    failures: list[BaseException] = []

    def submit() -> None:
        try:
            setup.orchestrator.submit(request)
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=submit, name="window-submit")
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    if failures:
        raise failures[0]


def _arm_unrelated_submit_before_the_recreate(setup: RunningBranch, sample_turn) -> ComputeScope:
    """Submit the second player's SHARED from another thread as the recovery's SHARED submit opens.

    That fresh plan refreshes readiness across the DAG after BRANCH_B's
    demotion and before the recreated SHARED registers.
    """
    other_shared = _other_player_shared_scope(setup, sample_turn)

    def submit_other_shared() -> None:
        _submit_from_another_thread(setup, ComputeRequest(ctx=setup.ctx, scope=other_shared))

    setup.shared_root_plan.arm(on_enter=submit_other_shared)
    return other_shared


def _assert_branch_waits_on_a_recreated_shared(
    setup: RunningBranch, superseded_shared: ComputeNodeRun, other_shared: ComputeScope
) -> None:
    """The window submit ran, and BRANCH_B waits on a running recreation of SHARED."""
    assert setup.orchestrator.nodes[other_shared].state == "running"
    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "waiting_deps"
    assert branch_superseded_execution(setup) == superseded_shared.execution_ref
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not superseded_shared
    assert recreated_shared.state == "running"


def test_a_refresh_before_the_recreate_registers_does_not_cascade_the_superseded_failure(
    sample_turn,
):
    setup = running_branch(sample_turn)
    _fail_shared_while_branch_runs(setup, RuntimeError("superseded shared failed"))
    failed_shared = setup.orchestrator.nodes[setup.shared]
    other_shared = _arm_unrelated_submit_before_the_recreate(setup, sample_turn)

    persist_branch_step_deferred(setup, shared_recovery(setup))

    _assert_branch_waits_on_a_recreated_shared(setup, failed_shared, other_shared)
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": SHARED_ID})
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def test_a_failed_recreate_cascades_its_own_error_not_the_superseded_one(sample_turn):
    setup = running_branch(sample_turn)
    _fail_shared_while_branch_runs(setup, RuntimeError("superseded shared failed"))
    _arm_unrelated_submit_before_the_recreate(setup, sample_turn)
    persist_branch_step_deferred(setup, shared_recovery(setup))
    recreate_failure = RuntimeError("recreated shared failed")

    complete_running_pool_step(setup.orchestrator, setup.shared, error=recreate_failure)

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is recreate_failure


def test_a_refresh_before_the_recreate_registers_does_not_promote_on_the_superseded_complete(
    sample_turn,
):
    """A complete SHARED already persisted is re-run, and BRANCH_B waits for that run."""
    setup = running_branch(sample_turn)
    complete_shared = setup.orchestrator.nodes[setup.shared]
    assert complete_shared.state == "complete"
    FIXTURE_EXPORT_STATE.mark_persisted(SHARED_ID, make_export_scope(sample_turn))
    other_shared = _arm_unrelated_submit_before_the_recreate(setup, sample_turn)

    persist_branch_step_deferred(setup, shared_recovery(setup))

    _assert_branch_waits_on_a_recreated_shared(setup, complete_shared, other_shared)
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": SHARED_ID})
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def test_a_recovery_of_a_running_dependency_waits_on_that_execution(sample_turn):
    setup = running_branch(sample_turn)
    _replace_shared_underrunning_branch(setup)
    running_shared = setup.orchestrator.nodes[setup.shared]
    persist_deferred = record_lifecycle(setup.orchestrator, ("persist_deferred",))

    persist_branch_step_deferred(setup, shared_recovery(setup))

    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "waiting_deps"
    assert branch_superseded_execution(setup) is None
    assert [record.detail["supersededExecutionGeneration"] for record in persist_deferred] == [None]
    assert setup.orchestrator.nodes[setup.shared] is running_shared
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": SHARED_ID})
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def test_a_force_fresh_attach_before_the_recreate_does_not_recreate_the_superseded_abort(
    sample_turn,
):
    """The recreate-aborted walk leaves the superseded SHARED to the recovery submit."""
    setup = running_branch(sample_turn)
    _abort_shared_while_branch_runs(setup)
    aborted_shared = setup.orchestrator.nodes[setup.shared]

    def attach_branch_force_fresh() -> None:
        _submit_from_another_thread(
            setup, ComputeRequest(ctx=setup.ctx, scope=setup.branch, force_fresh=True)
        )

    setup.shared_root_plan.arm(on_enter=attach_branch_force_fresh)
    force_fresh_submits = record_lifecycle(
        setup.orchestrator, ("force_fresh_replace", "force_fresh_attach")
    )

    persist_branch_step_deferred(setup, shared_recovery(setup))

    assert [record.kind for record in force_fresh_submits if record.scope == setup.shared] == [
        "force_fresh_replace"
    ]
    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not aborted_shared
    assert recreated_shared.state == "running"


def _raise(error: BaseException):
    """A root plan action that raises ``error``."""

    def action() -> None:
        raise error

    return action


def _defer_with_a_raising_recovery_submit(
    setup: RunningBranch, caplog, submit_failure: BaseException
) -> None:
    """Defer BRANCH_B on SHARED; the recovery submit's ``submit_failure`` reaches the drain log."""
    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        persist_branch_step_deferred(setup, shared_recovery(setup))
    assert [record.exc_info[1] for record in caplog.records if record.exc_info] == [submit_failure]


def _assert_branch_failed_with(setup: RunningBranch, error: BaseException) -> None:
    """BRANCH_B failed with ``error``, released its waiter, and cascaded to ROOT."""
    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is error
    assert setup.branch_waiter.error is error
    assert setup.orchestrator.nodes[setup.root].state == "failed"
    assert setup.orchestrator.nodes[setup.root].error is error


def _assert_branch_waits_then_settles_on(setup: RunningBranch, shared_node: ComputeNodeRun) -> None:
    """BRANCH_B waits on the running ``shared_node``, and runs once it completes."""
    assert setup.orchestrator.nodes[setup.branch].state == "waiting_deps"
    assert setup.orchestrator.nodes[setup.shared] is shared_node
    assert shared_node.state == "running"
    complete_running_pool_step(setup.orchestrator, setup.shared, result_wire={"result": SHARED_ID})
    assert setup.orchestrator.nodes[setup.branch].state == "running"


def test_a_recovery_submit_refused_because_the_requester_ended_plans_nothing(sample_turn):
    setup = running_branch(sample_turn)
    complete_shared = setup.orchestrator.nodes[setup.shared]
    abort_error = ComputeScopeAbortedError("branch cancelled")

    def abort_branch() -> None:
        assert setup.orchestrator.abort_scope(setup.branch, abort_error)

    setup.shared_root_plan.arm(on_enter=abort_branch)
    refused = record_lifecycle(setup.orchestrator, ("dependency_submit_refused",))

    persist_branch_step_deferred(setup, shared_recovery(setup))

    assert setup.orchestrator.nodes[setup.shared] is complete_shared
    assert [(record.scope, record.detail["reason"]) for record in refused] == [
        (setup.branch, "requester_ended")
    ]
    branch_node = setup.orchestrator.nodes[setup.branch]
    assert branch_node.state == "failed"
    assert branch_node.error is abort_error


@pytest.mark.allows_contained_callback_errors
def test_a_recovery_submit_raising_before_registration_fails_the_node(sample_turn, caplog):
    setup = running_branch(sample_turn)
    complete_shared = setup.orchestrator.nodes[setup.shared]
    submit_failure = RuntimeError("recovery submit failed")
    setup.shared_root_plan.arm(on_enter=_raise(submit_failure))

    _defer_with_a_raising_recovery_submit(setup, caplog, submit_failure)

    assert setup.orchestrator.nodes[setup.shared] is complete_shared
    _assert_branch_failed_with(setup, submit_failure)


@pytest.mark.allows_contained_callback_errors
def test_a_recovery_plan_raising_leaves_the_superseded_node_and_fails_the_waiter(
    sample_turn, monkeypatch, caplog
):
    """Planning changes nothing, so the recovery scope still holds the superseded SHARED."""
    setup = running_branch(sample_turn)
    complete_shared = setup.orchestrator.nodes[setup.shared]
    plan_failure = RuntimeError("turn unavailable at plan time")

    def raise_plan_failure(*_args, **_kwargs) -> None:
        raise plan_failure

    monkeypatch.setattr(setup.orchestrator, "_decide_root_registration", raise_plan_failure)

    _defer_with_a_raising_recovery_submit(setup, caplog, plan_failure)

    assert setup.orchestrator.nodes[setup.shared] is complete_shared
    _assert_branch_failed_with(setup, plan_failure)


@pytest.mark.allows_contained_callback_errors
def test_a_recovery_submit_raising_leaves_the_node_waiting_on_a_running_dependency(
    sample_turn, caplog
):
    setup = running_branch(sample_turn)
    _replace_shared_underrunning_branch(setup)
    running_shared = setup.orchestrator.nodes[setup.shared]
    submit_failure = RuntimeError("recovery submit failed")
    setup.shared_root_plan.arm(on_enter=_raise(submit_failure))

    _defer_with_a_raising_recovery_submit(setup, caplog, submit_failure)

    assert branch_superseded_execution(setup) is None
    _assert_branch_waits_then_settles_on(setup, running_shared)


@pytest.mark.allows_contained_callback_errors
def test_a_recovery_whose_root_plan_refuses_the_plan_fails_the_waiter(sample_turn, caplog):
    setup = running_branch(sample_turn)
    complete_shared = setup.orchestrator.nodes[setup.shared]
    hook_failure = RuntimeError("root plan refused the plan")
    setup.shared_root_plan.arm(on_accept_plan=_raise(hook_failure))

    _defer_with_a_raising_recovery_submit(setup, caplog, hook_failure)

    assert setup.orchestrator.nodes[setup.shared] is complete_shared
    _assert_branch_failed_with(setup, hook_failure)


@pytest.mark.allows_contained_callback_errors
def test_a_recovery_submit_raising_after_registration_settles_on_the_replacement(
    sample_turn, caplog
):
    setup = running_branch(sample_turn)
    complete_shared = setup.orchestrator.nodes[setup.shared]
    hook_failure = RuntimeError("root plan hook failed")
    setup.shared_root_plan.arm(on_exit=_raise(hook_failure))

    _defer_with_a_raising_recovery_submit(setup, caplog, hook_failure)

    recreated_shared = setup.orchestrator.nodes[setup.shared]
    assert recreated_shared is not complete_shared
    _assert_branch_waits_then_settles_on(setup, recreated_shared)


@dataclass(frozen=True)
class HeldRecoverySubmit:
    """BRANCH_B demoted on a superseded complete SHARED, its recovery submit not yet run."""

    setup: RunningBranch
    node: ComputeNodeRun
    generation: int
    deferral: PersistDeferral


def _hold_recovery_submit(sample_turn, monkeypatch) -> HeldRecoverySubmit:
    setup = running_branch(sample_turn)
    held: list[tuple[ComputeNodeRun, int, PersistDeferral, ComputeRequest]] = []

    def hold(node, generation, deferral, request) -> None:
        held.append((node, generation, deferral, request))

    monkeypatch.setattr(setup.orchestrator, "_submit_recovery_dependency", hold)
    persist_branch_step_deferred(setup, shared_recovery(setup))
    [(node, generation, deferral, request)] = held
    assert node is setup.orchestrator.nodes[setup.branch]
    assert node.state == "waiting_deps"
    assert request.scope == setup.shared
    assert deferral is node.last_persist_deferral
    assert deferral.dependency_scope == setup.shared
    assert deferral.superseded == setup.orchestrator.nodes[setup.shared].execution_ref
    return HeldRecoverySubmit(setup, node, generation, deferral)


def _settle(held: HeldRecoverySubmit, error: BaseException, **overrides) -> None:
    arguments = {
        "node": held.node,
        "generation": held.generation,
        "deferral": held.deferral,
        **overrides,
    }
    held.setup.orchestrator._settle_failed_recovery_submit(error=error, **arguments)
    held.setup.orchestrator.drain_post_lock_callbacks()


def test_settling_a_failed_recovery_submit_fails_a_node_with_no_replacement(
    sample_turn, monkeypatch
):
    held = _hold_recovery_submit(sample_turn, monkeypatch)
    submit_failure = RuntimeError("recovery submit failed")

    _settle(held, submit_failure)

    _assert_branch_failed_with(held.setup, submit_failure)


def _assert_branch_left_waiting(held: HeldRecoverySubmit) -> None:
    assert held.node.error is None
    assert held.setup.branch_waiter.state == "attach_inflight"
    assert held.setup.branch_waiter.error is None


def test_settling_a_failed_recovery_submit_leaves_a_node_re_deferred_with_a_new_marker(
    sample_turn, monkeypatch
):
    """An earlier recovery submit, made while SHARED still ran, leaves the later one in charge."""
    held = _hold_recovery_submit(sample_turn, monkeypatch)

    earlier = replace(held.deferral, superseded=None)

    _settle(held, RuntimeError("earlier recovery submit failed"), deferral=earlier)

    assert held.node.state == "waiting_deps"
    _assert_branch_left_waiting(held)


def test_settling_a_failed_recovery_submit_leaves_a_node_that_is_not_waiting(
    sample_turn, monkeypatch
):
    held = _hold_recovery_submit(sample_turn, monkeypatch)
    with held.setup.orchestrator._condition:
        held.node.state = "ready"

    _settle(held, RuntimeError("recovery submit failed"))

    assert held.node.state == "ready"
    _assert_branch_left_waiting(held)


def test_settling_a_failed_recovery_submit_leaves_a_node_that_is_not_the_scopes_node(
    sample_turn, monkeypatch
):
    held = _hold_recovery_submit(sample_turn, monkeypatch)
    detached_copy = replace(held.node)

    _settle(held, RuntimeError("recovery submit failed"), node=detached_copy)

    assert detached_copy.state == "waiting_deps"
    assert held.node.state == "waiting_deps"
    _assert_branch_left_waiting(held)


def test_settling_a_failed_recovery_submit_leaves_a_node_whose_execution_ended(
    sample_turn, monkeypatch
):
    held = _hold_recovery_submit(sample_turn, monkeypatch)

    _settle(held, RuntimeError("recovery submit failed"), generation=held.generation + 1)

    assert held.node.state == "waiting_deps"
    _assert_branch_left_waiting(held)


def test_settling_a_failed_recovery_submit_leaves_a_node_whose_dependency_was_replaced(
    sample_turn, monkeypatch
):
    held = _hold_recovery_submit(sample_turn, monkeypatch)
    setup = held.setup
    setup.orchestrator.submit(ComputeRequest(ctx=setup.ctx, scope=setup.shared, force_fresh=True))
    replacement = setup.orchestrator.nodes[setup.shared]

    _settle(held, RuntimeError("recovery submit failed"))

    assert held.node.state == "waiting_deps"
    _assert_branch_left_waiting(held)
    _assert_branch_waits_then_settles_on(setup, replacement)
