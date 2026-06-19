"""Backend tests for in-place inference stream invalidation and reschedule."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    iter_scores_table_inference_events,
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        backend.put("games/628580/1/turns/111", json.load(handle))
    return backend


def _install_workerless_scheduler(monkeypatch: pytest.MonkeyPatch) -> InferenceRowScheduler:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)

    def _get_scheduler() -> InferenceRowScheduler:
        return scheduler

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_scheduler.get_inference_row_scheduler",
        _get_scheduler,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_rows.get_inference_row_scheduler",
        _get_scheduler,
    )
    return scheduler


def _stream_scope(sample_turn) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def _schedule_player_row(
    scheduler: InferenceRowScheduler,
    sample_turn,
    *,
    player_id: int,
    stream_token: str,
) -> ScheduledInferenceRow:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=1,
        stream_token=stream_token,
    )
    assert scheduled is not None
    return scheduled


def _attach_active_table_stream(
    sample_turn,
    scheduler: InferenceRowScheduler,
    player_ids: tuple[int, ...],
) -> tuple[
    InferenceTableStreamController,
    dict[int, ScheduledInferenceRow],
    set[str],
    threading.Event,
]:
    scope = _stream_scope(sample_turn)
    stream_token = scheduler.begin_scope(scope)
    controller = InferenceTableStreamController(
        scope=scope,
        stream_token=stream_token,
        turn=sample_turn,
        player_ids=player_ids,
        scheduler=scheduler,
        game_id=628580,
        perspective=1,
    )

    for player_id in player_ids:
        scheduled = _schedule_player_row(
            scheduler,
            sample_turn,
            player_id=player_id,
            stream_token=stream_token,
        )
        controller.register_scheduled_row(player_id, scheduled)

    controller.attach()
    return (
        controller,
        controller.scheduled_rows,
        controller.finished_run_ids,
        controller.wake_multiplex,
    )


def _run_ids_for_players(
    scheduler: InferenceRowScheduler,
    player_ids: tuple[int, ...],
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for run in scheduler._runs.values():
        if run.session.player_id in player_ids:
            mapping[run.session.player_id] = run.session.run_id
    return mapping


def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def test_mask_change_reschedules_in_flight_row_while_table_stream_active_case_3(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Case 3 backend: mask change cancels and reschedules one in-flight row."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    assert len(player_ids) == 2

    _attach_active_table_stream(sample_turn, scheduler, player_ids)
    persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(persistence, scheduler=scheduler)

    target_player_id, other_player_id = player_ids
    before = _run_ids_for_players(scheduler, player_ids)
    assert set(before) == set(player_ids)

    invalidation.on_hull_mask_changed(
        628580,
        1,
        sample_turn.settings.turn,
        target_player_id,
    )

    after = _run_ids_for_players(scheduler, player_ids)
    assert after[target_player_id] != before[target_player_id]
    assert after[other_player_id] == before[other_player_id]
    cancelled_run = scheduler._runs.get(before[target_player_id])
    assert cancelled_run is None or cancelled_run.session.cancel_token.is_cancelled()
    assert persistence.get_row(628580, 1, sample_turn.settings.turn, target_player_id) is None


def test_mask_change_reschedules_completed_row_while_table_stream_active_case_4(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Case 4 backend: mask change reschedules a completed row on an open stream."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])

    _active_stream, scheduled_rows, finished_run_ids, _wake = _attach_active_table_stream(
        sample_turn,
        scheduler,
        player_ids,
    )
    persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(persistence, scheduler=scheduler)

    target_player_id, other_player_id = player_ids
    completed_row = scheduled_rows[target_player_id]
    finished_run_ids.add(completed_row.session.run_id)

    before_other_run_id = scheduled_rows[other_player_id].session.run_id
    before_target_run_id = completed_row.session.run_id

    invalidation.on_hull_mask_changed(
        628580,
        1,
        sample_turn.settings.turn,
        target_player_id,
    )

    assert scheduled_rows[other_player_id].session.run_id == before_other_run_id
    assert scheduled_rows[target_player_id].session.run_id != before_target_run_id
    assert before_target_run_id not in finished_run_ids
    assert persistence.get_row(628580, 1, sample_turn.settings.turn, target_player_id) is None


def test_recompute_reschedules_all_rows_while_table_stream_active_cases_1_and_2(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Cases 1/2 backend: recompute clears persistence and reschedules every open-stream row."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn

    _attach_active_table_stream(sample_turn, scheduler, player_ids)
    persistence = InferenceRowPersistenceService(memory_backend)
    for player_id in player_ids:
        persistence.put_row(
            628580,
            1,
            turn_number,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary=f"cached-{player_id}",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
        )

    before = _run_ids_for_players(scheduler, player_ids)
    invalidation = InferenceInvalidationService(persistence, scheduler=scheduler)
    invalidation.recompute_host_turn(628580, 1, turn_number)

    after = _run_ids_for_players(scheduler, player_ids)
    assert set(after) == set(player_ids)
    assert after != before
    for player_id in player_ids:
        assert persistence.get_row(628580, 1, turn_number, player_id) is None


def test_mask_change_integration_via_table_stream_generator_case_3(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Integration: invalidation while iter_scores_table_inference_events multiplex is active."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(persistence, scheduler=scheduler)

    stream = iter_scores_table_inference_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        persistence=persistence,
    )
    assert next(stream) == {"type": "globalPause", "paused": False}

    def consume_stream() -> None:
        try:
            for _event in stream:
                pass
        finally:
            stream.close()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()
    _wait_until(lambda: len(_run_ids_for_players(scheduler, player_ids)) == len(player_ids))

    target_player_id, other_player_id = player_ids
    before = _run_ids_for_players(scheduler, player_ids)
    invalidation.on_hull_mask_changed(628580, 1, turn_number, target_player_id)

    _wait_until(
        lambda: (
            _run_ids_for_players(scheduler, player_ids).get(target_player_id)
            != before[target_player_id]
        )
    )
    after = _run_ids_for_players(scheduler, player_ids)
    assert after[other_player_id] == before[other_player_id]
    assert persistence.get_row(628580, 1, turn_number, target_player_id) is None

    thread.join(timeout=2.0)


def _seed_cached_rows(
    persistence: InferenceRowPersistenceService,
    *,
    turn_number: int,
    player_ids: tuple[int, ...],
) -> None:
    for player_id in player_ids:
        persistence.put_row(
            628580,
            1,
            turn_number,
            player_id,
            PersistedInferenceRow(
                status=STATUS_EXACT,
                summary=f"cached-{player_id}",
                solution_count=0,
                is_complete=True,
                solutions=[],
            ),
        )


def test_all_cached_replay_keeps_stream_open_for_mask_invalidation_case_4_integration(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """After every row replays from cache, mask change still reschedules on the open stream."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(persistence, scheduler=scheduler)
    _seed_cached_rows(persistence, turn_number=turn_number, player_ids=player_ids)

    stream = iter_scores_table_inference_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        persistence=persistence,
    )
    events: list[dict[str, object]] = []
    stream_closed = threading.Event()
    scope = _stream_scope(sample_turn)

    def consume_stream() -> None:
        try:
            for event in stream:
                events.append(event)
        finally:
            stream.close()
            stream_closed.set()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()

    _wait_until(
        lambda: sum(1 for event in events if event.get("type") == "complete") >= len(player_ids)
    )
    assert len(scheduler._runs) == 0
    assert not stream_closed.is_set()
    assert controller_for_scope(scope) is not None

    target_player_id, other_player_id = player_ids
    invalidation.on_hull_mask_changed(628580, 1, turn_number, target_player_id)

    _wait_until(lambda: target_player_id in _run_ids_for_players(scheduler, player_ids))
    assert other_player_id not in _run_ids_for_players(scheduler, (other_player_id,))
    assert persistence.get_row(628580, 1, turn_number, target_player_id) is None

    rescheduled_run = scheduler._runs[_run_ids_for_players(scheduler, player_ids)[target_player_id]]
    rescheduled_run.session.event_queue.put(
        row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="after mask on cached row",
        )
    )

    _wait_until(
        lambda: any(
            event.get("type") == "complete"
            and event.get("playerId") == target_player_id
            and event.get("summary") == "after mask on cached row"
            for event in events
        )
    )
    cached_other_events = [
        event
        for event in events
        if event.get("type") == "complete"
        and event.get("playerId") == other_player_id
        and event.get("summary") == f"cached-{other_player_id}"
    ]
    assert len(cached_other_events) == 1

    scheduler.begin_scope(scope)
    thread.join(timeout=2.0)


def test_all_cached_replay_keeps_stream_open_for_recompute_cases_1_and_2_integration(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """After every row replays from cache, recompute reschedules all rows on the open stream."""
    reset_inference_table_stream_registry_for_tests()
    scheduler = _install_workerless_scheduler(monkeypatch)
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    persistence = InferenceRowPersistenceService(memory_backend)
    invalidation = InferenceInvalidationService(persistence, scheduler=scheduler)
    _seed_cached_rows(persistence, turn_number=turn_number, player_ids=player_ids)

    stream = iter_scores_table_inference_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        persistence=persistence,
    )
    scope = _stream_scope(sample_turn)
    events: list[dict[str, object]] = []
    stream_closed = threading.Event()

    def consume_stream() -> None:
        try:
            for event in stream:
                events.append(event)
        finally:
            stream.close()
            stream_closed.set()

    thread = threading.Thread(target=consume_stream, daemon=True)
    thread.start()

    _wait_until(
        lambda: sum(1 for event in events if event.get("type") == "complete") >= len(player_ids)
    )
    assert not stream_closed.is_set()
    assert controller_for_scope(scope) is not None

    invalidation.recompute_host_turn(628580, 1, turn_number)

    _wait_until(lambda: len(_run_ids_for_players(scheduler, player_ids)) == len(player_ids))
    for player_id in player_ids:
        assert persistence.get_row(628580, 1, turn_number, player_id) is None

    scheduler.begin_scope(scope)
    thread.join(timeout=2.0)
