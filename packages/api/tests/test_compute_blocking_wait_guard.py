"""Blocking orchestrator waits refuse to run inside a post-lock drain or a step.

A wait inside a drain could block on work that only the suspended drain on
the same thread would run, and steps never wait by design. ``ensure_scopes``,
``run_until_idle`` and ``ComputeHandle.wait`` raise ``NestedBlockingWaitError``
there, before planning or waiting, however far the awaited work has got.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from api.compute import (
    ComputeOrchestrator,
    ComputeRequest,
    ComputeWorkerPool,
    build_compute_registry,
)
from api.compute.errors import NestedBlockingWaitError

from tests.compute_orchestrator_fixtures import (
    inline_compute_registration,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.fixtures.export_framework.chain_exports import CHAIN_ID
from tests.fixtures.export_framework.diamond_exports import BRANCH_B_ID, SHARED_ID
from tests.fixtures.export_framework.harness import (
    CHAIN_FIXTURE_EXPORT_REGISTRY,
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    build_stored_turn_chain,
    make_fixture_query_context,
)

OBSERVERS_LOGGER = "api.compute.orchestrator_observers"


def _diamond(sample_turn):
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    export_scope = make_export_scope(sample_turn)
    return (
        ctx,
        make_compute_scope(SHARED_ID, export_scope),
        make_compute_scope(BRANCH_B_ID, export_scope),
    )


def _inline_orchestrator(*registrations) -> ComputeOrchestrator:
    return ComputeOrchestrator(compute_registry=build_compute_registry(registrations))


def _errors_inside_a_drain(orchestrator: ComputeOrchestrator, blocking_call) -> list[type]:
    """Run ``blocking_call`` from a post-lock callback; return what it raised."""
    raised: list[type] = []

    def callback() -> None:
        try:
            blocking_call()
        except Exception as error:
            raised.append(type(error))

    with orchestrator.observers.condition:
        orchestrator.observers.schedule_post_lock(callback)
    orchestrator.drain_post_lock_callbacks()
    return raised


def test_ensure_scope_inside_a_drain_raises_before_planning(sample_turn):
    ctx, shared, _branch = _diamond(sample_turn)
    orchestrator = _inline_orchestrator(inline_compute_registration(SHARED_ID))

    raised = _errors_inside_a_drain(
        orchestrator, lambda: orchestrator.ensure_scope(ComputeRequest(ctx=ctx, scope=shared))
    )

    assert raised == [NestedBlockingWaitError]
    assert shared not in orchestrator.nodes


def test_run_until_idle_inside_a_drain_raises(sample_turn):
    orchestrator = _inline_orchestrator(inline_compute_registration(SHARED_ID))

    raised = _errors_inside_a_drain(orchestrator, orchestrator.run_until_idle)

    assert raised == [NestedBlockingWaitError]


def test_waiting_on_an_already_terminal_handle_inside_a_drain_raises(sample_turn):
    ctx, shared, _branch = _diamond(sample_turn)
    orchestrator = _inline_orchestrator(inline_compute_registration(SHARED_ID))
    handle = orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared))
    assert handle.state == "complete"

    raised = _errors_inside_a_drain(orchestrator, handle.wait)

    assert raised == [NestedBlockingWaitError]
    assert handle.wait() is handle


@pytest.mark.allows_post_lock_callback_errors
def test_a_blocking_wait_escaping_a_callback_is_logged_and_the_drain_goes_on(sample_turn, caplog):
    ctx, shared, _branch = _diamond(sample_turn)
    orchestrator = _inline_orchestrator(inline_compute_registration(SHARED_ID))
    ran_after: list[str] = []

    with orchestrator.observers.condition:
        orchestrator.observers.schedule_post_lock(
            lambda: orchestrator.ensure_scope(ComputeRequest(ctx=ctx, scope=shared))
        )
        orchestrator.observers.schedule_post_lock(lambda: ran_after.append("next"))
    with caplog.at_level(logging.ERROR, logger=OBSERVERS_LOGGER):
        orchestrator.drain_post_lock_callbacks()

    assert ran_after == ["next"]
    [record] = [record for record in caplog.records if record.name == OBSERVERS_LOGGER]
    assert record.exc_info is not None
    assert record.exc_info[0] is NestedBlockingWaitError


def _ensuring_inline_registration(analytic_id, orchestrator_cell, request_cell, *, in_builder):
    """An inline step that ensures another scope from its wire build or its step."""
    registration = inline_compute_registration(analytic_id)

    def ensure_other() -> None:
        orchestrator_cell[0].ensure_scope(request_cell[0])

    def build(scope, **_kwargs):
        if in_builder:
            ensure_other()
        return {"scope": scope.analytic_id}

    def run_step(job):
        if not in_builder:
            ensure_other()
        return {"result": job["scope"]}

    return replace(
        registration,
        build_step_job_wires=(("materialize", build),),
        run_steps=(("materialize", run_step),),
    )


@pytest.mark.parametrize("in_builder", [False, True], ids=["run_step", "wire_build"])
def test_an_inline_step_at_the_head_of_a_chain_that_waits_fails_its_node(sample_turn, in_builder):
    ctx, shared, branch = _diamond(sample_turn)
    orchestrator_cell: list[ComputeOrchestrator] = []
    request_cell = [ComputeRequest(ctx=ctx, scope=branch)]
    orchestrator = _inline_orchestrator(
        _ensuring_inline_registration(
            SHARED_ID, orchestrator_cell, request_cell, in_builder=in_builder
        ),
        inline_compute_registration(BRANCH_B_ID),
    )
    orchestrator_cell.append(orchestrator)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared))

    node = orchestrator.nodes[shared]
    assert node.state == "failed"
    assert isinstance(node.error, NestedBlockingWaitError)


def test_an_inline_step_mid_chain_that_waits_fails_its_node(sample_turn):
    turns = 3
    stored = build_stored_turn_chain(sample_turn, through_turn=turns)
    ctx = make_fixture_query_context(
        stored[turns],
        stored_turns=stored,
        registry=CHAIN_FIXTURE_EXPORT_REGISTRY,
        enforce_inline_ensure_threshold=False,
    )
    root = make_compute_scope(CHAIN_ID, make_export_scope(stored[turns]))
    middle = replace(root, turn=2)
    orchestrator_cell: list[ComputeOrchestrator] = []

    def run_step(job):
        if job["turn"] == middle.turn:
            orchestrator_cell[0].ensure_scope(ComputeRequest(ctx=ctx, scope=replace(root, turn=1)))
        return {"result": job["scope"]}

    registration = replace(
        inline_compute_registration(CHAIN_ID),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": CHAIN_ID, "turn": scope.turn}),
        ),
        run_steps=(("materialize", run_step),),
    )
    orchestrator = _inline_orchestrator(registration)
    orchestrator_cell.append(orchestrator)

    orchestrator.submit(ComputeRequest(ctx=ctx, scope=root))

    assert orchestrator.nodes[replace(root, turn=1)].state == "complete"
    assert isinstance(orchestrator.nodes[middle].error, NestedBlockingWaitError)


def test_a_thread_pool_step_that_waits_fails_its_node(sample_turn):
    ctx, shared, branch = _diamond(sample_turn)
    pool = ComputeWorkerPool(worker_count=0)
    orchestrator_cell: list[ComputeOrchestrator] = []

    def run_step(job):
        orchestrator_cell[0].ensure_scope(ComputeRequest(ctx=ctx, scope=branch))
        return job

    registration = replace(
        pool_compute_registration(SHARED_ID, backend="thread"),
        run_steps=(("materialize", run_step),),
    )
    try:
        orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry(
                (registration, inline_compute_registration(BRANCH_B_ID))
            ),
            worker_pool=pool,
        )
        orchestrator_cell.append(orchestrator)
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=shared))
        picked = pool.take_next_item_for_tests()
        assert picked is not None

        pool._execute_item(picked)
    finally:
        pool.shutdown()

    node = orchestrator.nodes[shared]
    assert node.state == "failed"
    assert isinstance(node.error, NestedBlockingWaitError)
