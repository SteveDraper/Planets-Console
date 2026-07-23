"""Reproduce scores reschedule_row holding stream_lock across schedule (0% CPU).

Fingerprint (game 680224, turn 11): pool workers stuck inFlight with timeline
frozen after mid-tier completes; UI rows stay in-progress with no CPU.

Fleet already fixed the sibling hang: ``FleetTableStreamController.reschedule_player``
must not hold ``stream_lock`` across ``dispatch_admission`` / schedule / orchestrator
submit (see ``test_reschedule_player_does_not_deadlock_when_schedule_reenters_invalidation``).

Scores ``InferenceTableStreamController.reschedule_row`` still holds ``stream_lock``
across ``register_admitted_schedule`` → ``schedule_player_row`` → ``enqueue_tier_ladder``
(and submit when not deferred). Nested ``deliver_domain_event`` / ``reschedule_row``
needs the same non-reentrant lock and self-deadlocks.
"""

from __future__ import annotations

import concurrent.futures

import pytest
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    ScheduleRowAdmission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import reset_orchestrators_for_tests
from api.streaming.table_stream.row_stream_resolution_registry import (
    clear_stream_resolutions,
)


@pytest.fixture(autouse=True)
def _reset_state(request):
    reset_inference_table_stream_registry_for_tests()
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    clear_stream_resolutions()

    def cleanup() -> None:
        reset_inference_table_stream_registry_for_tests()
        reset_tier_row_run_registry_for_tests()
        reset_orchestrators_for_tests()
        reset_compute_worker_pool_for_tests(worker_count=1)
        clear_stream_resolutions()

    request.addfinalizer(cleanup)


def _session(sample_turn, *, player_id: int) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def test_reschedule_row_does_not_hold_stream_lock_across_schedule(
    sample_turn,
    monkeypatch,
) -> None:
    """Schedule under stream_lock must not re-enter reschedule (fleet parity).

    Production hang: ``reschedule_row`` held ``stream_lock`` across
    ``register_admitted_schedule`` → ``schedule_player_row``. Nested invalidation /
    domain delivery / another ``reschedule_row`` blocks forever on the same
    non-reentrant lock (0% CPU; turn-11 workers stuck behind wedged inFlight).
    """
    player_id = sample_turn.scores[0].ownerid
    stream_scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
    stream_token = scheduler.begin_scope(stream_scope)
    controller = InferenceTableStreamController(
        scope=stream_scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=(player_id,),
        scheduler=scheduler,
        game_id=stream_scope.game_id,
        perspective=stream_scope.perspective,
    )
    controller.attach()

    monkeypatch.setattr(
        controller,
        "resolve_row_admission",
        lambda _player_id, **_kwargs: ScheduleRowAdmission(),
    )

    nest_depth = {"n": 0}

    def schedule_that_reenters_reschedule(_player_id: int) -> ScheduledInferenceRow:
        nest_depth["n"] += 1
        if nest_depth["n"] == 1:
            # Same-thread re-entry fingerprint: nested work while outer reschedule
            # still holds stream_lock (before the lock-order fix).
            acquired = controller.stream_lock.acquire(blocking=False)
            if not acquired:
                raise AssertionError(
                    "reschedule_row deadlocked (schedule re-entered stream_lock "
                    "via nested scores invalidation / re-admit; 680224 turn-11 hang)"
                )
            controller.stream_lock.release()
            assert controller.reschedule_row(player_id) is True
        session = _session(sample_turn, player_id=player_id)
        return ScheduledInferenceRow(player_id=player_id, session=session)

    monkeypatch.setattr(controller, "schedule_player_row", schedule_that_reenters_reschedule)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(controller.reschedule_row, player_id)
        try:
            assert future.result(timeout=5.0) is True
        except concurrent.futures.TimeoutError as exc:
            raise AssertionError(
                "reschedule_row deadlocked (held stream_lock across schedule; "
                "680224 turn-11 hang fingerprint)"
            ) from exc

    assert nest_depth["n"] >= 2
    assert player_id in controller.scheduled_rows
