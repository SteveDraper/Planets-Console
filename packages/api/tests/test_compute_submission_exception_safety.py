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
from tests.fixtures.export_framework.diamond_exports import SHARED_ID
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
