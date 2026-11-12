"""A raising post-lock callback does not cost its peers in the same drain."""

from __future__ import annotations

import logging
import threading

import pytest
from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry
from api.compute.orchestrator_observers import OrchestratorObservers
from api.compute.wire import StepResult

from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import BRANCH_B_ID, SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)
from tests.post_lock_callback_guard import failing_on_post_lock_callback_errors
from tests.test_compute_foundation import _StubPersistencePolicy
from tests.test_compute_orchestrator import (
    _compute_scope,
    _export_scope,
    _pool_compute_registration,
)

OBSERVERS_LOGGER = "api.compute.orchestrator_observers"


class _PostLockCallbackFailed(RuntimeError):
    pass


def _raise_post_lock_failure() -> None:
    raise _PostLockCallbackFailed("reschedule failed")


def _callback_failure_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == OBSERVERS_LOGGER]


@pytest.mark.allows_post_lock_callback_errors
def test_a_raising_callback_does_not_drop_the_rest_of_its_batch(caplog):
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    ran: list[str] = []
    with condition:
        observers.schedule_post_lock(_raise_post_lock_failure)
        observers.schedule_post_lock(lambda: ran.append("later"))

    with caplog.at_level(logging.ERROR, logger=OBSERVERS_LOGGER):
        observers.drain_post_lock_callbacks()

    assert ran == ["later"]
    [record] = _callback_failure_records(caplog)
    assert "_raise_post_lock_failure" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is _PostLockCallbackFailed


@pytest.mark.allows_post_lock_callback_errors
def test_callbacks_a_survivor_schedules_still_run_in_the_same_drain(caplog):
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    ran: list[str] = []

    def schedule_follow_up() -> None:
        with condition:
            observers.schedule_post_lock(lambda: ran.append("follow-up"))

    with condition:
        observers.schedule_post_lock(_raise_post_lock_failure)
        observers.schedule_post_lock(schedule_follow_up)

    with caplog.at_level(logging.ERROR, logger=OBSERVERS_LOGGER):
        observers.drain_post_lock_callbacks()

    assert ran == ["follow-up"]
    assert len(_callback_failure_records(caplog)) == 1


class _PersistWithRaisingNotification(_StubPersistencePolicy):
    """Persist succeeds and hands back a notification that raises after complete."""

    def persist(self, _ctx, _scope, _result_wire):
        return _raise_post_lock_failure


@pytest.mark.allows_post_lock_callback_errors
def test_dependents_dispatch_when_a_post_lock_callback_raises_after_a_dependency_completes(
    sample_turn, caplog
):
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    export_scope = _export_scope(sample_turn)
    dispatched: list[str] = []
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                _pool_compute_registration(
                    SHARED_ID,
                    backend="thread",
                    persistence_policy=_PersistWithRaisingNotification(),
                ),
                _pool_compute_registration(BRANCH_B_ID, backend="thread"),
            )
        ),
        pool_submitter=lambda node, _step, **_kwargs: dispatched.append(node.scope.analytic_id),
    )
    shared_scope = _compute_scope(SHARED_ID, export_scope)
    branch_scope = _compute_scope(BRANCH_B_ID, export_scope)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=branch_scope))
    assert dispatched == [SHARED_ID]

    with caplog.at_level(logging.ERROR, logger=OBSERVERS_LOGGER):
        complete_running_pool_step(
            orchestrator,
            shared_scope,
            result_wire=StepResult(outcome="persist", payload={"result": SHARED_ID}),
        )

    assert orchestrator.nodes[shared_scope].state == "complete"
    assert orchestrator.nodes[branch_scope].state == "running"
    assert dispatched == [SHARED_ID, BRANCH_B_ID]
    assert len(_callback_failure_records(caplog)) == 1


@pytest.mark.allows_post_lock_callback_errors
def test_the_suite_guard_fails_a_test_whose_callback_raises_on_another_thread():
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    with condition:
        observers.schedule_post_lock(_raise_post_lock_failure)
    drainer = threading.Thread(target=observers.drain_post_lock_callbacks)

    with pytest.raises(pytest.fail.Exception) as guard_failure:
        with failing_on_post_lock_callback_errors():
            drainer.start()
            drainer.join()

    report = str(guard_failure.value)
    assert "_raise_post_lock_failure" in report
    assert "_PostLockCallbackFailed: reschedule failed" in report
