"""Inference global pause holds work only at the dispatch gate; clearing pause releases it.

A stream-owned run registered while paused is accepted and submitted like any
other. The pause gate holds its ``tier_solve`` node in the ready queue, and
clearing pause runs one dispatch pass.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    SCORES_OFF_LOCK_THREAD_NAME,
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_domain_events import WorkAccepted
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE
from api.compute.orchestrator_state import ComputeRequest
from api.compute.pools import ComputeWorkerPool, reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.services import inference_invalidation_service
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService

from tests.scores_exports_helpers import scores_query_context, stream_scope_for_turn
from tests.scores_row_lifecycle_test_helpers import _patch_scores_dag_without_fleet_deps
from tests.table_stream_test_helpers import IdleStream, connect_idle_stream, end_stream_inline


@pytest.fixture
def workerless_pool(monkeypatch: pytest.MonkeyPatch) -> Iterator[ComputeWorkerPool]:
    """A pool with no workers, so a dispatched step waits in the pool queue."""
    reset_inference_row_scheduler_for_tests()
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    yield pool
    reset_inference_row_scheduler_for_tests()


@pytest.fixture
def scheduler(make_inference_scheduler) -> InferenceRowScheduler:
    return make_inference_scheduler()


def _session(sample_turn, persistence, scheduler, player_index: int) -> InferenceRowStreamSession:
    score = sample_turn.scores[player_index]
    scope = stream_scope_for_turn(sample_turn)
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn_number,
        query_context=scores_query_context(
            sample_turn, persistence=persistence, scheduler=scheduler
        ),
    )


def _root_scope(sample_turn, player_index: int) -> ComputeScope:
    scope = stream_scope_for_turn(sample_turn)
    return scope.root_scope(sample_turn.scores[player_index].ownerid)


def _pool_scopes(pool: ComputeWorkerPool) -> set[ComputeScope]:
    return {queued.item.scope for queued in pool.snapshot_work_queue()}


def _submit_gate_held_nodes(sample_turn, persistence, scheduler) -> tuple[ComputeScope, ...]:
    """Submit a tier_solve per scoreboard row straight to the orchestrator, as continuations are."""
    orchestrator = get_compute_orchestrator()
    ctx = scores_query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    held = tuple(_root_scope(sample_turn, index) for index in range(len(sample_turn.scores)))
    for root_scope in held:
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope, step_kind=SCORES_TIER_SOLVE))
    return held


def test_a_run_accepted_while_paused_waits_at_the_gate_until_resume(
    sample_turn, persistence, workerless_pool, scheduler
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    token = scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    session = _session(sample_turn, persistence, scheduler, 0)
    root_scope = _root_scope(sample_turn, 0)

    scheduler.enqueue_tier_ladder(session, stream_token=token)
    scheduler.accept_pending_run(session.run_id)

    orchestrator = get_compute_orchestrator()
    assert root_scope in orchestrator.ready_scopes()
    assert _pool_scopes(workerless_pool) == set()
    assert scheduler.global_pause_status(scope)["heldJobCount"] == 1

    scheduler.resume_globally(scope)

    assert root_scope not in orchestrator.ready_scopes()
    assert _pool_scopes(workerless_pool) == {root_scope}


def test_held_job_count_reads_the_gate_orchestrator_without_a_stream_binding(
    sample_turn, persistence, workerless_pool, scheduler
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    for index in range(len(sample_turn.scores)):
        scheduler.enqueue_tier_ladder(_session(sample_turn, persistence, scheduler, index))

    held = _submit_gate_held_nodes(sample_turn, persistence, scheduler)

    assert scheduler._stream_bindings == {}
    assert scheduler.global_pause_status(scope)["heldJobCount"] == len(held)


def test_a_claim_at_another_turn_while_paused_dispatches_the_gate_held_nodes(
    sample_turn, persistence, workerless_pool, scheduler
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    held = _submit_gate_held_nodes(sample_turn, persistence, scheduler)
    assert _pool_scopes(workerless_pool) == set()

    scheduler.begin_scope(stream_scope_for_turn(sample_turn, turn_number=scope.turn_number + 1))

    assert _pool_scopes(workerless_pool) == set(held)


def test_a_late_end_of_a_replaced_stream_leaves_the_paused_successors_work(
    sample_turn, persistence, workerless_pool, scheduler
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    replaced_token = scheduler.begin_scope(scope)
    replaced_session = _session(sample_turn, persistence, scheduler, 0)
    scheduler.enqueue_tier_ladder(replaced_session, stream_token=replaced_token)

    successor_token = scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    successor_session = _session(sample_turn, persistence, scheduler, 0)
    scheduler.enqueue_tier_ladder(successor_session, stream_token=successor_token)
    scheduler.accept_pending_run(successor_session.run_id)

    end_stream_inline(scheduler, scope, replaced_token)

    assert scheduler.global_pause_status(scope)["paused"] is True
    assert _pool_scopes(workerless_pool) == set()

    scheduler.resume_globally(scope)

    assert _pool_scopes(workerless_pool) == {_root_scope(sample_turn, 0)}


@pytest.mark.parametrize("is_stream_paused", [False, True], ids=["running", "paused"])
def test_detach_discards_a_pending_accept(
    sample_turn, persistence, workerless_pool, scheduler, monkeypatch, is_stream_paused
) -> None:
    submitted: list[ComputeScope] = []
    monkeypatch.setattr(
        scheduler,
        "_submit_tier_solve",
        lambda _binding, root_scope: submitted.append(root_scope),
    )
    scope = stream_scope_for_turn(sample_turn)
    token = scheduler.begin_scope(scope)
    if is_stream_paused:
        scheduler.pause_globally(scope)
    session = _session(sample_turn, persistence, scheduler, 0)
    scheduler.enqueue_tier_ladder(session, stream_token=token)

    scheduler.detach_inference_stream(scope, stream_token=token)
    scheduler.accept_pending_run(session.run_id)

    assert submitted == []


def _install_recompute(
    sample_turn,
    memory_backend,
    scheduler: InferenceRowScheduler,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reschedule_error: Exception | None = None,
) -> tuple[InferenceInvalidationService, list[bool]]:
    """An invalidation service whose reschedule records whether pause was still set."""
    paused_at_reschedule: list[bool] = []

    def record_reschedule(scope, *, force_schedule: bool) -> None:
        del scope, force_schedule
        paused_at_reschedule.append(scheduler._globally_paused)
        if reschedule_error is not None:
            raise reschedule_error

    monkeypatch.setattr(
        inference_invalidation_service, "reschedule_all_inference_rows", record_reschedule
    )
    persistence = InferenceRowPersistenceService(memory_backend)
    return InferenceInvalidationService(persistence, scheduler=scheduler), paused_at_reschedule


def test_recompute_reschedules_while_paused_then_releases_pause(
    sample_turn, memory_backend, workerless_pool, scheduler, monkeypatch
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    invalidation, paused_at_reschedule = _install_recompute(
        sample_turn, memory_backend, scheduler, monkeypatch
    )

    invalidation.recompute_host_turn(scope.game_id, scope.perspective, scope.turn_number)

    assert paused_at_reschedule == [True]
    assert scheduler.global_pause_status(scope)["paused"] is False


def test_recompute_releases_pause_when_the_reschedule_raises(
    sample_turn, memory_backend, workerless_pool, scheduler, monkeypatch
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    invalidation, _paused_at_reschedule = _install_recompute(
        sample_turn,
        memory_backend,
        scheduler,
        monkeypatch,
        reschedule_error=RuntimeError("reschedule failed"),
    )

    with pytest.raises(RuntimeError, match="reschedule failed"):
        invalidation.recompute_host_turn(scope.game_id, scope.perspective, scope.turn_number)

    assert scheduler.global_pause_status(scope)["paused"] is False


# --- A stream's connect close releases pause on the scheduler's off-lock runner ---

RELEASE_WAIT_SECONDS = 2.0


def _wait_until(predicate, timeout: float = RELEASE_WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@dataclass(frozen=True)
class HeldReleasePass:
    """The runner thread's release pass, held until the test sets ``release``.

    ``entered`` is set when the pass starts and ``resumed`` when it saw ``release``
    in time; the test asserts both on its own thread.
    """

    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    resumed: threading.Event = field(default_factory=threading.Event)


def _hold_release_pass(
    scheduler: InferenceRowScheduler, monkeypatch: pytest.MonkeyPatch
) -> HeldReleasePass:
    """Make the runner thread's release pass wait until the returned pass is released."""
    held = HeldReleasePass()
    attachment = scheduler._orchestrator_attachment
    real_registered = attachment.registered_orchestrator

    def registered_orchestrator():
        if threading.current_thread().name == SCORES_OFF_LOCK_THREAD_NAME:
            held.entered.set()
            if held.release.wait(RELEASE_WAIT_SECONDS):
                held.resumed.set()
        return real_registered()

    monkeypatch.setattr(attachment, "registered_orchestrator", registered_orchestrator)
    return held


def _accepted_paused_row(sample_turn, persistence, scheduler, token, player_index: int = 0):
    session = _session(sample_turn, persistence, scheduler, player_index)
    scheduler.enqueue_tier_ladder(session, stream_token=token)
    scheduler.accept_pending_run(session.run_id)
    return session


def _open_paused_stream(scheduler: InferenceRowScheduler, scope) -> IdleStream:
    """Open an idle stream at ``scope`` through the connect, then pause globally."""
    opened = connect_idle_stream(scheduler, scope)
    scheduler.pause_globally(scope)
    return opened


def test_a_close_while_paused_dispatches_the_gate_held_nodes(
    sample_turn, persistence, workerless_pool, scheduler
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    opened = _open_paused_stream(scheduler, scope)
    _accepted_paused_row(sample_turn, persistence, scheduler, opened.stream_token)
    root_scope = _root_scope(sample_turn, 0)
    assert root_scope in get_compute_orchestrator().ready_scopes()

    opened.stream.close()

    assert scheduler.off_lock_runner.drain(timeout=RELEASE_WAIT_SECONDS)
    assert _pool_scopes(workerless_pool) == {root_scope}
    assert root_scope not in get_compute_orchestrator().ready_scopes()


def test_a_close_under_the_orchestrator_lock_returns_and_releases_afterwards(
    sample_turn, persistence, workerless_pool, scheduler
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    opened = _open_paused_stream(scheduler, scope)
    _accepted_paused_row(sample_turn, persistence, scheduler, opened.stream_token)
    root_scope = _root_scope(sample_turn, 0)
    orchestrator = get_compute_orchestrator()
    close = threading.Thread(target=opened.stream.close)

    with orchestrator._condition:
        close.start()
        close.join(RELEASE_WAIT_SECONDS)
        close_returned_under_the_lock = not close.is_alive()

    assert close_returned_under_the_lock
    assert scheduler.off_lock_runner.drain(timeout=RELEASE_WAIT_SECONDS)
    assert _pool_scopes(workerless_pool) == {root_scope}


def test_a_reopen_before_the_close_releases_gets_no_work_from_the_old_stream(
    sample_turn, persistence, workerless_pool, scheduler, monkeypatch
) -> None:
    """A structural guard: the closed stream's release pass submits nothing of its own.

    The pass only dispatches what the gate holds, so after it runs the pool holds
    the row's single tier_solve and the reopened stream sees exactly one
    WorkAccepted, its own.
    """
    scope = stream_scope_for_turn(sample_turn)
    closed = _open_paused_stream(scheduler, scope)
    _accepted_paused_row(sample_turn, persistence, scheduler, closed.stream_token)
    held = _hold_release_pass(scheduler, monkeypatch)
    closed.stream.close()
    assert held.entered.wait(RELEASE_WAIT_SECONDS)

    reopened_token = scheduler.begin_scope(scope)
    reopened_session = _accepted_paused_row(sample_turn, persistence, scheduler, reopened_token)
    held.release.set()
    assert held.resumed.wait(RELEASE_WAIT_SECONDS)

    root_scope = _root_scope(sample_turn, 0)
    assert _wait_until(lambda: _pool_scopes(workerless_pool) == {root_scope})
    reopened_events = []
    while not reopened_session.event_queue.empty():
        reopened_events.append(reopened_session.event_queue.get_nowait())
    assert [type(event) for event in reopened_events].count(WorkAccepted) == 1


def test_shutdown_with_a_release_pending_registers_nothing_again(
    sample_turn, persistence, workerless_pool, scheduler, monkeypatch
) -> None:
    scope = stream_scope_for_turn(sample_turn)
    opened = _open_paused_stream(scheduler, scope)
    _accepted_paused_row(sample_turn, persistence, scheduler, opened.stream_token)
    orchestrator = get_compute_orchestrator()
    held = _hold_release_pass(scheduler, monkeypatch)
    opened.stream.close()
    assert held.entered.wait(RELEASE_WAIT_SECONDS)

    shutdown = threading.Thread(target=scheduler.shutdown)
    shutdown.start()
    held.release.set()
    shutdown.join(RELEASE_WAIT_SECONDS)

    assert held.resumed.is_set()
    assert not shutdown.is_alive()
    assert scheduler._orchestrator_attachment.registered_orchestrator() is None
    assert scheduler._pause_dispatch_gate not in orchestrator.observers.dispatch_gates
