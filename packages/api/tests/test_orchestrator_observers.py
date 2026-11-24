"""A raising observer callback does not cost its peers, and never reaches the notifier.

Post-lock callbacks, ready-queue listeners and inline-start listeners each run
even when an earlier one raises; the failure is logged with the callback named.
"""

from __future__ import annotations

import logging
import threading

import pytest
from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry
from api.compute.orchestrator_observers import OrchestratorObservers
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import StepResult

from tests.compute_orchestrator_fixtures import (
    RecordingPoolSubmitter,
    StubPersistencePolicy,
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
from tests.observer_callback_guard import failing_on_observer_callback_errors

OBSERVERS_LOGGER = "api.compute.orchestrator_observers"


class _PostLockCallbackFailed(RuntimeError):
    pass


def _raise_post_lock_failure() -> None:
    raise _PostLockCallbackFailed("reschedule failed")


def _callback_failure_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == OBSERVERS_LOGGER]


@pytest.mark.allows_observer_callback_errors
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


@pytest.mark.allows_observer_callback_errors
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


class _PersistWithRaisingNotification(StubPersistencePolicy):
    """Persist succeeds and hands back a notification that raises after complete."""

    def persist(self, _ctx, _scope, _result_wire):
        return _raise_post_lock_failure


@pytest.mark.allows_observer_callback_errors
def test_dependents_dispatch_when_a_post_lock_callback_raises_after_a_dependency_completes(
    sample_turn, caplog
):
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    export_scope = make_export_scope(sample_turn)
    pool_submitter = RecordingPoolSubmitter()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                pool_compute_registration(
                    SHARED_ID,
                    backend="thread",
                    persistence_policy=_PersistWithRaisingNotification(),
                ),
                pool_compute_registration(BRANCH_B_ID, backend="thread"),
            )
        ),
        pool_submitter=pool_submitter,
    )
    shared_scope = make_compute_scope(SHARED_ID, export_scope)
    branch_scope = make_compute_scope(BRANCH_B_ID, export_scope)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=branch_scope))
    assert pool_submitter.submissions == [(shared_scope, "materialize")]

    with caplog.at_level(logging.ERROR, logger=OBSERVERS_LOGGER):
        complete_running_pool_step(
            orchestrator,
            shared_scope,
            result_wire=StepResult(outcome="persist", payload={"result": SHARED_ID}),
        )

    assert orchestrator.nodes[shared_scope].state == "complete"
    assert orchestrator.nodes[branch_scope].state == "running"
    assert pool_submitter.submissions == [
        (shared_scope, "materialize"),
        (branch_scope, "materialize"),
    ]
    assert len(_callback_failure_records(caplog)) == 1


@pytest.mark.allows_observer_callback_errors
def test_the_suite_guard_fails_a_test_whose_callback_raises_on_another_thread():
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    with condition:
        observers.schedule_post_lock(_raise_post_lock_failure)
    drainer = threading.Thread(target=observers.drain_post_lock_callbacks)

    with pytest.raises(pytest.fail.Exception) as guard_failure:
        with failing_on_observer_callback_errors():
            drainer.start()
            drainer.join()

    report = str(guard_failure.value)
    assert "_raise_post_lock_failure" in report
    assert "_PostLockCallbackFailed: reschedule failed" in report


class _ListenerFailed(RuntimeError):
    pass


def _raise_ready_queue_failure(_ready_scopes) -> None:
    raise _ListenerFailed("ready-queue listener failed")


def _raise_inline_start_failure(_scope, _node, _step_kind) -> None:
    raise _ListenerFailed("inline-start listener failed")


def _assert_one_logged_failure(caplog, *, role: str, listener_name: str) -> None:
    [record] = _callback_failure_records(caplog)
    assert role in record.getMessage()
    assert listener_name in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is _ListenerFailed


@pytest.mark.allows_observer_callback_errors
def test_a_raising_ready_queue_listener_is_logged_and_later_listeners_still_run(
    sample_turn, caplog
):
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    scope = make_compute_scope(SHARED_ID, make_export_scope(sample_turn))
    received: list[tuple] = []
    observers.register_ready_queue_listener(_raise_ready_queue_failure)
    observers.register_ready_queue_listener(received.append)

    with caplog.at_level(logging.ERROR, logger=OBSERVERS_LOGGER):
        with condition:
            observers.notify_ready_queue_changed((scope,))

    assert received == [(scope,)]
    _assert_one_logged_failure(
        caplog, role="Ready-queue listener", listener_name="_raise_ready_queue_failure"
    )


@pytest.mark.allows_observer_callback_errors
def test_a_raising_inline_start_listener_is_logged_and_later_listeners_still_run(
    sample_turn, caplog
):
    condition = threading.Condition()
    observers = OrchestratorObservers(condition)
    scope = make_compute_scope(SHARED_ID, make_export_scope(sample_turn))
    node = ComputeNodeRun(scope=scope, dependency_scopes=(), submission_open=SubmissionOpen())
    received: list[tuple] = []
    observers.register_inline_start_listener(_raise_inline_start_failure)
    observers.register_inline_start_listener(
        lambda started_scope, started_node, step_kind: received.append(
            (started_scope, started_node, step_kind)
        )
    )

    with caplog.at_level(logging.ERROR, logger=OBSERVERS_LOGGER):
        observers.notify_inline_start(node, "materialize")

    assert received == [(scope, node, "materialize")]
    _assert_one_logged_failure(
        caplog, role="Inline-start listener", listener_name="_raise_inline_start_failure"
    )
