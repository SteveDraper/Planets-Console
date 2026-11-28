"""Root-plan blocks hold after-root-plans work until the outermost block on the thread exits.

``submit`` and ``ensure_scopes`` plan inside a root-plan block. Work handed to
``run_after_root_plans`` while one is open waits for the outermost exit on
that thread, where it runs after one drain, each callback contained; with no
block open it runs at once after a drain. ``queue_scope_abort`` is
``abort_scope`` without the drain, so its listeners precede held work.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import replace

import pytest
from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry
from api.compute.errors import ComputeScopeAbortedError, NestedRootPlanSubmitError
from api.compute.orchestrator_observers import OrchestratorObservers
from api.services.in_flight_orchestrator import in_flight_orchestrator

from tests.compute_orchestrator_fixtures import (
    ArmableRootPlanHook,
    RecordingPoolSubmitter,
    StubPersistencePolicy,
    inline_compute_registration,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)

CONTAINMENT_LOGGER = "api.callback_containment"


class _HeldCallbackFailed(RuntimeError):
    pass


class _BlockInterrupted(BaseException):
    pass


def _raise_held_failure() -> None:
    raise _HeldCallbackFailed("re-admit failed")


def _observers() -> tuple[threading.Condition, OrchestratorObservers]:
    condition = threading.Condition()
    return condition, OrchestratorObservers(condition)


def _failure_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == CONTAINMENT_LOGGER]


def test_held_work_waits_for_the_outermost_of_nested_blocks():
    _condition, observers = _observers()
    ran: list[str] = []

    with observers.root_plan_block():
        with observers.root_plan_block():
            observers.run_after_root_plans(lambda: ran.append("held"))
        assert ran == []
    assert ran == ["held"]


def test_with_no_block_open_the_callback_runs_at_once_after_a_drain():
    condition, observers = _observers()
    ran: list[str] = []
    with condition:
        observers.schedule_post_lock(lambda: ran.append("queued"))

    observers.run_after_root_plans(lambda: ran.append("callback"))

    assert ran == ["queued", "callback"]


@pytest.mark.allows_contained_callback_errors
def test_a_callback_run_at_once_that_raises_is_contained_and_logged(caplog):
    _condition, observers = _observers()

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        observers.run_after_root_plans(_raise_held_failure)

    [record] = _failure_records(caplog)
    assert record.exc_info is not None
    assert record.exc_info[0] is _HeldCallbackFailed


@pytest.mark.allows_contained_callback_errors
def test_held_work_runs_in_order_and_past_a_failure(caplog):
    _condition, observers = _observers()
    ran: list[str] = []

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        with observers.root_plan_block():
            observers.run_after_root_plans(lambda: ran.append("first"))
            observers.run_after_root_plans(_raise_held_failure)
            observers.run_after_root_plans(lambda: ran.append("third"))

    assert ran == ["first", "third"]
    assert len(_failure_records(caplog)) == 1


def test_held_work_still_runs_when_the_block_exits_by_an_exception():
    _condition, observers = _observers()
    ran: list[str] = []

    with pytest.raises(_HeldCallbackFailed):
        with observers.root_plan_block():
            observers.run_after_root_plans(lambda: ran.append("held"))
            _raise_held_failure()

    assert ran == ["held"]


def test_held_work_is_dropped_when_the_block_exits_by_an_interrupt():
    _condition, observers = _observers()
    ran: list[str] = []

    with pytest.raises(_BlockInterrupted):
        with observers.root_plan_block():
            observers.run_after_root_plans(lambda: ran.append("dropped"))
            raise _BlockInterrupted

    with observers.root_plan_block():
        observers.run_after_root_plans(lambda: ran.append("next block"))
    assert ran == ["next block"]


def test_a_held_callback_that_opens_a_block_runs_its_own_held_work_first():
    _condition, observers = _observers()
    ran: list[str] = []

    def plan_again() -> None:
        ran.append("outer first")
        with observers.root_plan_block():
            observers.run_after_root_plans(lambda: ran.append("nested"))

    with observers.root_plan_block():
        observers.run_after_root_plans(plan_again)
        observers.run_after_root_plans(lambda: ran.append("outer second"))

    assert ran == ["outer first", "nested", "outer second"]


def test_held_work_runs_on_the_holding_thread_and_another_thread_runs_its_own_at_once():
    _condition, observers = _observers()
    ran: list[tuple[str, str]] = []

    def record(name: str) -> None:
        ran.append((name, threading.current_thread().name))

    def other_thread() -> None:
        observers.run_after_root_plans(lambda: record("other"))

    with observers.root_plan_block():
        observers.run_after_root_plans(lambda: record("held"))
        worker = threading.Thread(target=other_thread, name="other-thread")
        worker.start()
        worker.join()
        assert ran == [("other", "other-thread")]

    assert ran == [("other", "other-thread"), ("held", threading.current_thread().name)]


def test_a_block_inside_a_drain_still_holds_until_it_exits():
    condition, observers = _observers()
    ran: list[str] = []

    def drained() -> None:
        with observers.root_plan_block():
            observers.run_after_root_plans(lambda: ran.append("held"))
            assert ran == []
        ran.append("after block")

    with condition:
        observers.schedule_post_lock(drained)
    observers.drain_post_lock_callbacks()

    assert ran == ["held", "after block"]


def test_the_submit_guard_raises_inside_a_block_and_not_inside_held_work():
    _condition, observers = _observers()
    ran: list[str] = []

    def held() -> None:
        observers.reject_submit_in_root_plan("submit")
        ran.append("held passed the guard")

    observers.reject_submit_in_root_plan("submit")
    with observers.root_plan_block():
        with pytest.raises(NestedRootPlanSubmitError) as error:
            observers.reject_submit_in_root_plan("submit")
        observers.run_after_root_plans(held)

    assert error.value.operation == "submit"
    assert ran == ["held passed the guard"]


def _ctx(sample_turn):
    return make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)


def _shared_scope(sample_turn):
    return make_compute_scope(SHARED_ID, make_export_scope(sample_turn))


def _pool_orchestrator(root_plan_hook: ArmableRootPlanHook | None = None):
    registration = pool_compute_registration(SHARED_ID, backend="thread")
    if root_plan_hook is not None:
        registration = replace(registration, open_root_plan=root_plan_hook)
    return ComputeOrchestrator(
        compute_registry=build_compute_registry((registration,)),
        pool_submitter=RecordingPoolSubmitter(),
    )


def _running_node_with_abort_listener(sample_turn, ran: list[str]):
    """A pool orchestrator with one running node and a listener that records its abort."""
    orchestrator = _pool_orchestrator()
    scope = _shared_scope(sample_turn)
    orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))
    orchestrator.observers.register_lifecycle_listener(
        lambda kind, *_rest: ran.append(kind) if kind == "abort" else None
    )
    return orchestrator, scope


def test_queue_scope_abort_queues_the_listeners_without_draining(sample_turn):
    ran: list[str] = []
    orchestrator, scope = _running_node_with_abort_listener(sample_turn, ran)

    assert orchestrator.queue_scope_abort(scope, ComputeScopeAbortedError("cancelled"))

    assert orchestrator.nodes[scope].state == "failed"
    assert ran == []
    orchestrator.drain_post_lock_callbacks()
    assert ran == ["abort"]


def test_abort_scope_drains_the_listeners_it_queued(sample_turn):
    ran: list[str] = []
    orchestrator, scope = _running_node_with_abort_listener(sample_turn, ran)

    assert orchestrator.abort_scope(scope, ComputeScopeAbortedError("cancelled"))

    assert ran == ["abort"]


def test_queue_scope_abort_of_another_execution_changes_nothing(sample_turn):
    ran: list[str] = []
    orchestrator, scope = _running_node_with_abort_listener(sample_turn, ran)
    generation = orchestrator.nodes[scope].execution_generation

    assert not orchestrator.queue_scope_abort(
        scope,
        ComputeScopeAbortedError("cancelled"),
        expected_execution_generation=generation + 1,
    )

    assert orchestrator.nodes[scope].state == "running"


def test_outside_a_drain_the_queued_abort_listeners_run_before_held_work(sample_turn):
    ran: list[str] = []
    orchestrator, scope = _running_node_with_abort_listener(sample_turn, ran)

    with orchestrator.observers.root_plan_block():
        orchestrator.queue_scope_abort(scope, ComputeScopeAbortedError("cancelled"))
        orchestrator.run_after_root_plans(lambda: ran.append("re-admit"))

    assert ran == ["abort", "re-admit"]


def test_inside_an_outer_drain_held_work_runs_before_the_queued_abort_listeners(sample_turn):
    ran: list[str] = []
    orchestrator, scope = _running_node_with_abort_listener(sample_turn, ran)

    def drained() -> None:
        with orchestrator.observers.root_plan_block():
            orchestrator.queue_scope_abort(scope, ComputeScopeAbortedError("cancelled"))
            orchestrator.run_after_root_plans(lambda: ran.append("re-admit"))

    with orchestrator.observers.condition:
        orchestrator.observers.schedule_post_lock(drained)
    orchestrator.drain_post_lock_callbacks()

    assert ran == ["re-admit", "abort"]


def test_submit_holds_work_until_its_root_plan_closes_and_its_dispatch_pass_ran(sample_turn):
    hook = ArmableRootPlanHook()
    orchestrator = _pool_orchestrator(hook)
    scope = _shared_scope(sample_turn)
    ran: list[str] = []

    def hold() -> None:
        with pytest.raises(NestedRootPlanSubmitError):
            orchestrator.observers.reject_submit_in_root_plan("submit")
        orchestrator.run_after_root_plans(
            lambda: ran.append(f"held saw {orchestrator.nodes[scope].state}")
        )

    hook.arm(on_enter=hold, on_exit=lambda: ran.append("plan closed"))
    orchestrator.submit(ComputeRequest(ctx=_ctx(sample_turn), scope=scope))

    assert ran == ["plan closed", "held saw running"]


def test_ensure_scopes_holds_work_until_its_root_plans_close(sample_turn):
    hook = ArmableRootPlanHook()
    registration = replace(inline_compute_registration(SHARED_ID), open_root_plan=hook)
    orchestrator = ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))
    scope = _shared_scope(sample_turn)
    ran: list[str] = []

    hook.arm(
        on_enter=lambda: orchestrator.run_after_root_plans(lambda: ran.append("held")),
        on_exit=lambda: ran.append("plan closed"),
    )
    (handle,) = orchestrator.ensure_scopes((ComputeRequest(ctx=_ctx(sample_turn), scope=scope),))

    assert handle.error is None
    assert ran == ["plan closed", "held"]


class _SatisfiedAtPerspective(StubPersistencePolicy):
    """Satisfied for one perspective only, so an ensure batch mixes satisfied and unsatisfied."""

    def __init__(self, perspective: int) -> None:
        self._perspective = perspective

    def is_satisfied(self, _ctx, scope) -> bool:
        return scope.perspective == self._perspective


def test_ensure_scopes_submits_its_satisfied_scopes_outside_the_root_plan_block(sample_turn):
    hook = ArmableRootPlanHook()
    registration = replace(
        inline_compute_registration(SHARED_ID),
        open_root_plan=hook,
        persistence_policy=_SatisfiedAtPerspective(1),
    )
    orchestrator = ComputeOrchestrator(compute_registry=build_compute_registry((registration,)))
    export_scope = make_export_scope(sample_turn)
    satisfied = make_compute_scope(SHARED_ID, replace(export_scope, perspective=1))
    unsatisfied = make_compute_scope(SHARED_ID, replace(export_scope, perspective=2))
    ran: list[str] = []

    def held_from_satisfied_submit() -> None:
        ran.append(f"held; unsatisfied registered: {unsatisfied in orchestrator.nodes}")

    hook.arm(
        for_scope=satisfied,
        on_enter=lambda: orchestrator.run_after_root_plans(held_from_satisfied_submit),
    )
    ctx = _ctx(sample_turn)
    orchestrator.ensure_scopes(
        (ComputeRequest(ctx=ctx, scope=satisfied), ComputeRequest(ctx=ctx, scope=unsatisfied))
    )

    # Inside the batch's block the held work would wait until the unsatisfied
    # root registered; outside it, it runs as the satisfied submit returns.
    assert ran == ["held; unsatisfied registered: False"]
    assert unsatisfied in orchestrator.nodes


@pytest.mark.allows_contained_callback_errors
def test_the_absent_orchestrator_stand_in_runs_at_once_and_contains(caplog):
    stand_in = in_flight_orchestrator(None)
    ran: list[str] = []

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        stand_in.run_after_root_plans(lambda: ran.append("ran"))
        stand_in.run_after_root_plans(_raise_held_failure)

    assert ran == ["ran"]
    [record] = _failure_records(caplog)
    assert record.exc_info is not None
    assert record.exc_info[0] is _HeldCallbackFailed
