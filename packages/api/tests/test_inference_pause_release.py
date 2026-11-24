"""Inference global pause holds work only at the dispatch gate; clearing pause releases it.

A stream-owned run registered while paused is accepted and submitted like any
other. The pause gate holds its ``tier_solve`` node in the ready queue, and
clearing pause runs one dispatch pass.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
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


@pytest.fixture
def workerless_pool(monkeypatch: pytest.MonkeyPatch) -> Iterator[ComputeWorkerPool]:
    """A pool with no workers, so a dispatched step waits in the pool queue."""
    reset_inference_row_scheduler_for_tests()
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    yield pool
    reset_inference_row_scheduler_for_tests()


@pytest.fixture
def scheduler() -> Iterator[InferenceRowScheduler]:
    scheduler = InferenceRowScheduler()
    yield scheduler
    scheduler.shutdown()


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

    scheduler.detach_inference_stream(scope, (replaced_session,), stream_token=replaced_token)
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

    scheduler.detach_inference_stream(scope, (session,), stream_token=token)
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
