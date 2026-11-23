"""Submission exception safety.

Submission registers work and schedules a dispatch pass; it never marks a
node ``running`` itself. Each entry point drains the post-lock queue in a
``finally``, so work it registered is dispatched even when the root plan
raises on the way out, and a raise inside that pass is logged rather than
hiding the submission's own outcome.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry
from api.compute.errors import ComputeWaitTimeoutError
from api.compute.wire import StepResult

from tests.compute_orchestrator_fixtures import (
    ArmableRootPlanHook,
    RecordingPoolSubmitter,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import BRANCH_B_ID, SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)


class _ExitError(RuntimeError):
    pass


class _GateError(RuntimeError):
    pass


def _raise_exit_error() -> None:
    raise _ExitError("root plan exit failed")


def _ctx(sample_turn):
    return make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)


def _shared_scopes(sample_turn, count: int):
    export_scope = make_export_scope(sample_turn)
    return tuple(
        make_compute_scope(SHARED_ID, replace(export_scope, perspective=perspective))
        for perspective in range(1, count + 1)
    )


def _pool_orchestrator(root_plan_hook=None):
    registration = pool_compute_registration(SHARED_ID, backend="thread")
    if root_plan_hook is not None:
        registration = replace(registration, open_root_plan=root_plan_hook)
    submitter = RecordingPoolSubmitter()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((registration,)),
        pool_submitter=submitter,
    )
    return orchestrator, submitter


def test_a_root_plan_exit_that_raises_still_dispatches_the_registered_pool_step(sample_turn):
    (scope,) = _shared_scopes(sample_turn, 1)
    hook = ArmableRootPlanHook()
    orchestrator, submitter = _pool_orchestrator(hook)
    hook.arm(on_exit=_raise_exit_error)

    with pytest.raises(_ExitError):
        orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))

    assert orchestrator.nodes[scope].state == "running"
    assert submitter.submissions == [(scope, "materialize")]


def test_an_ensure_batch_whose_root_plan_exit_raises_still_dispatches_its_pool_steps(sample_turn):
    scopes = _shared_scopes(sample_turn, 2)
    hook = ArmableRootPlanHook()
    orchestrator, submitter = _pool_orchestrator(hook)
    hook.arm(on_exit=_raise_exit_error)
    ctx = _ctx(sample_turn)

    with pytest.raises(_ExitError):
        orchestrator.ensure_scopes(tuple(ComputeRequest(ctx=ctx, scope=scope) for scope in scopes))

    assert sorted(submitter.submissions, key=str) == sorted(
        ((scope, "materialize") for scope in scopes), key=str
    )


def test_an_ensure_batch_puts_every_pool_root_in_flight(sample_turn):
    scopes = _shared_scopes(sample_turn, 3)
    orchestrator, submitter = _pool_orchestrator()
    ctx = _ctx(sample_turn)

    with pytest.raises(ComputeWaitTimeoutError):
        orchestrator.ensure_scopes(
            tuple(ComputeRequest(ctx=ctx, scope=scope) for scope in scopes),
            timeout=0.01,
        )

    assert {scope for scope, _step_kind in submitter.submissions} == set(scopes)
    assert all(orchestrator.nodes[scope].state == "running" for scope in scopes)


def test_waking_a_parked_node_dispatches_it_before_returning(sample_turn):
    (scope,) = _shared_scopes(sample_turn, 1)
    orchestrator, submitter = _pool_orchestrator()
    ctx = _ctx(sample_turn)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    complete_running_pool_step(
        orchestrator,
        scope,
        result_wire=StepResult(outcome="park", park_reason="waiting"),
    )
    assert orchestrator.nodes[scope].state == "parked"

    handle = orchestrator.wake_if_parked(ComputeRequest(ctx=ctx, scope=scope, force_fresh=True))

    assert handle is not None
    assert orchestrator.nodes[scope].state == "running"
    assert submitter.submissions == [(scope, "materialize"), (scope, "materialize")]


def test_a_force_fresh_attach_that_readies_a_waiting_node_dispatches_it_before_returning(
    sample_turn,
):
    """The attach refreshes the waiting node's readiness and schedules the pass that runs it.

    The dependent is left ``waiting_deps`` with no dependency still pending,
    as when its dependencies settled without reaching it, so only the
    ``force_fresh`` attach makes it ready.
    """
    export_scope = make_export_scope(sample_turn)
    shared = make_compute_scope(SHARED_ID, export_scope)
    dependent = make_compute_scope(BRANCH_B_ID, export_scope)
    submitter = RecordingPoolSubmitter()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                pool_compute_registration(SHARED_ID, backend="thread"),
                pool_compute_registration(BRANCH_B_ID, backend="thread"),
            )
        ),
        pool_submitter=submitter,
    )
    ctx = _ctx(sample_turn)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=dependent))
    assert orchestrator.nodes[dependent].state == "waiting_deps"
    orchestrator.nodes[dependent].dependency_scopes = ()

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=dependent, force_fresh=True))

    assert orchestrator.nodes[dependent].state == "running"
    assert submitter.submissions == [(shared, "materialize"), (dependent, "materialize")]


@pytest.mark.allows_post_lock_callback_errors
def test_a_gate_that_raises_in_the_submitters_pass_does_not_fail_the_submit(sample_turn):
    (scope,) = _shared_scopes(sample_turn, 1)
    orchestrator, submitter = _pool_orchestrator()

    def gate(_node) -> bool:
        raise _GateError("gate failed")

    orchestrator.observers.register_dispatch_gate(gate)

    handle = orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))

    assert handle.state == "ready"
    assert submitter.submissions == []


class _AcceptError(RuntimeError):
    pass


def _raise_accept_error() -> None:
    raise _AcceptError("root plan refused the plan")


def _record_lifecycle_kinds(orchestrator: ComputeOrchestrator) -> list[str]:
    kinds: list[str] = []
    orchestrator.observers.register_lifecycle_listener(
        lambda kind, *_args, **_kwargs: kinds.append(kind)
    )
    return kinds


def test_a_refused_force_fresh_plan_leaves_the_terminal_node_in_place(sample_turn):
    (scope,) = _shared_scopes(sample_turn, 1)
    hook = ArmableRootPlanHook()
    orchestrator, submitter = _pool_orchestrator(hook)
    ctx = _ctx(sample_turn)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    complete_running_pool_step(
        orchestrator, scope, result_wire=StepResult(outcome="complete", payload={})
    )
    terminal = orchestrator.nodes[scope]
    assert terminal.state == "complete"
    lifecycle_kinds = _record_lifecycle_kinds(orchestrator)
    hook.arm(on_accept_plan=_raise_accept_error)

    with pytest.raises(_AcceptError):
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, force_fresh=True))

    assert orchestrator.nodes[scope] is terminal
    assert "force_fresh_replace" not in lifecycle_kinds
    assert submitter.submissions == [(scope, "materialize")]


def test_an_ensure_batch_whose_second_plan_is_refused_runs_only_the_first(sample_turn):
    first, second, third = _shared_scopes(sample_turn, 3)
    hook = ArmableRootPlanHook()
    orchestrator, submitter = _pool_orchestrator(hook)
    hook.arm(for_scope=second, on_accept_plan=_raise_accept_error)
    ctx = _ctx(sample_turn)

    with pytest.raises(_AcceptError):
        orchestrator.ensure_scopes(
            tuple(ComputeRequest(ctx=ctx, scope=scope) for scope in (first, second, third))
        )

    assert submitter.submissions == [(first, "materialize")]
    assert second not in orchestrator.nodes
    assert third not in orchestrator.nodes


def test_a_refused_ensure_plan_leaves_a_hollow_terminal_root_in_place(sample_turn):
    (scope,) = _shared_scopes(sample_turn, 1)
    ctx = _ctx(sample_turn)
    # The stub persistence policy is never satisfied, so a complete node at
    # the scope is a hollow terminal for ensure.
    hook = ArmableRootPlanHook()
    orchestrator, _submitter = _pool_orchestrator(hook)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    complete_running_pool_step(
        orchestrator, scope, result_wire=StepResult(outcome="complete", payload={})
    )
    hollow = orchestrator.nodes[scope]
    hook.arm(on_accept_plan=_raise_accept_error)

    with pytest.raises(_AcceptError):
        orchestrator.ensure_scopes((ComputeRequest(ctx=ctx, scope=scope),))

    assert orchestrator.nodes[scope] is hollow


def test_an_ensure_replaces_a_failed_terminal_root_instead_of_reraising_its_error(sample_turn):
    (scope,) = _shared_scopes(sample_turn, 1)
    orchestrator, submitter = _pool_orchestrator()
    ctx = _ctx(sample_turn)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    complete_running_pool_step(orchestrator, scope, error=RuntimeError("old failure"))
    assert orchestrator.nodes[scope].state == "failed"

    with pytest.raises(ComputeWaitTimeoutError):
        orchestrator.ensure_scopes((ComputeRequest(ctx=ctx, scope=scope),), timeout=0.01)

    assert orchestrator.nodes[scope].state == "running"
    assert len(submitter.submissions) == 2


def test_a_plain_submit_reuses_a_terminal_root(sample_turn):
    (scope,) = _shared_scopes(sample_turn, 1)
    orchestrator, submitter = _pool_orchestrator()
    ctx = _ctx(sample_turn)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    complete_running_pool_step(
        orchestrator, scope, result_wire=StepResult(outcome="complete", payload={})
    )
    terminal = orchestrator.nodes[scope]

    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))

    assert handle.state == "complete"
    assert orchestrator.nodes[scope] is terminal
    assert submitter.submissions == [(scope, "materialize")]
