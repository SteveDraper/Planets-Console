"""Characterization tests for inference stream lifecycle gaps (persist vs deliver).

These tests document edge cases in the stream/multiplex/preempt path where terminal
row state may be persisted or finalized on the backend while the NDJSON consumer
never receives a ``complete`` event. They use injected events and failures only --
no production code changes.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    RowComplete,
    RowCompleteWirePayload,
    TierProgress,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    iter_multiplexed_inference_events,
    iter_scores_table_inference_events,
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.scope import ComputeScope
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

ASSETS_DIR = Path(__file__).resolve().parent.parent / "api" / "storage" / "assets"


def _diagnostics(*, turn: int, player_id: int) -> dict[str, object]:
    return {
        "turn": turn,
        "constraints": {"playerId": player_id, "turn": turn},
        "solver": {"status": STATUS_EXACT, "solver_status": "OPTIMAL"},
    }


def _row_complete(
    *,
    summary: str,
    diagnostics: dict[str, object] | None = None,
) -> RowComplete:
    wire_diagnostics = diagnostics or {}
    return RowComplete(
        result=InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics=wire_diagnostics),
        wire_payload=RowCompleteWirePayload(
            status=STATUS_EXACT,
            summary=summary,
            solution_count=1,
            is_complete=True,
            solutions=[],
            diagnostics=wire_diagnostics,
        ),
    )


def _session_for_player(sample_turn, *, player_id: int) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )


def _scheduled_row(sample_turn, *, player_id: int) -> ScheduledInferenceRow:
    return ScheduledInferenceRow(
        player_id=player_id,
        session=_session_for_player(sample_turn, player_id=player_id),
    )


def _install_workerless_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_row_complete: Callable | None = None,
) -> InferenceRowScheduler:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(
        worker_count=0,
        on_row_complete=on_row_complete,
    )

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


def _complete_row_via_scheduler(
    scheduler: InferenceRowScheduler,
    session: InferenceRowStreamSession,
    row_complete: RowComplete,
    *,
    persistence: InferenceRowPersistenceService | None = None,
) -> None:
    if persistence is not None:
        persistence.persist_row_complete(session, row_complete)
    session.event_queue.put(row_complete)
    scheduler._finalize_row_run(session)


def _wait_until(predicate: Callable[[], bool], *, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def _collect_stream_events(stream: Iterator[dict[str, object]]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    try:
        for event in stream:
            events.append(event)
    finally:
        stream.close()
    return events


@pytest.fixture
def memory_backend():
    backend = MemoryAssetBackend(initial={})
    with open(ASSETS_DIR / "game_info_sample.json") as handle:
        backend.put("games/628580/info", json.load(handle))
    with open(ASSETS_DIR / "turn_sample.json") as handle:
        backend.put("games/628580/1/turns/111", json.load(handle))
    return backend


def test_multiplex_stops_when_scope_deactivates_before_queued_complete_is_yielded(sample_turn):
    """Queued terminal events for pending rows are dropped when the stream scope ends."""
    fast_row = _scheduled_row(sample_turn, player_id=sample_turn.scores[0].ownerid)
    slow_row = _scheduled_row(sample_turn, player_id=sample_turn.scores[1].ownerid)
    fast_row.session.event_queue.put(_row_complete(summary="fast complete"))
    slow_row.session.event_queue.put(
        _row_complete(
            summary="slow complete never delivered",
            diagnostics=_diagnostics(turn=sample_turn.settings.turn, player_id=slow_row.player_id),
        )
    )

    scope_active = True

    def is_stream_active() -> bool:
        return scope_active

    stream = iter_multiplexed_inference_events(
        (fast_row, slow_row),
        tag_player_id=True,
        is_stream_active=is_stream_active,
    )
    first = next(stream)
    assert first["type"] == "complete"
    assert first["playerId"] == fast_row.player_id

    scope_active = False
    remaining = list(stream)

    assert remaining == []
    slow_types = [
        event["type"] for event in remaining if event.get("playerId") == slow_row.player_id
    ]
    assert "complete" not in slow_types


def test_multiplex_delivers_all_queued_completes_before_scope_deactivation(sample_turn):
    """Baseline: both rows receive terminal events when the scope stays active."""
    rows = tuple(
        _scheduled_row(sample_turn, player_id=player_id)
        for player_id in (row.ownerid for row in sample_turn.scores[:2])
    )
    for row in rows:
        row.session.event_queue.put(
            _row_complete(
                summary=f"player {row.player_id} complete",
                diagnostics=_diagnostics(turn=sample_turn.settings.turn, player_id=row.player_id),
            )
        )

    events = list(
        iter_multiplexed_inference_events(
            rows,
            tag_player_id=True,
        )
    )
    complete_player_ids = {
        event["playerId"]
        for event in events
        if event.get("type") == "complete" and isinstance(event.get("playerId"), int)
    }
    assert complete_player_ids == {row.player_id for row in rows}


def test_stream_reconnect_preempts_first_connection_while_rows_compute(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Reconnect preempts the prior stream so a duplicate connect can proceed."""
    persistence = InferenceRowPersistenceService(memory_backend)
    scheduler = _install_workerless_scheduler(
        monkeypatch,
        on_row_complete=persistence.persist_row_complete,
    )
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    completed_player_id = player_ids[0]
    in_flight_player_id = player_ids[1]
    turn_number = sample_turn.settings.turn

    first_token = scheduler.begin_scope(scope)
    completed_session = _session_for_player(sample_turn, player_id=completed_player_id)
    in_flight_session = _session_for_player(sample_turn, player_id=in_flight_player_id)
    scheduler.enqueue_tier_ladder(completed_session, stream_token=first_token)
    scheduler.enqueue_tier_ladder(in_flight_session, stream_token=first_token)

    _complete_row_via_scheduler(
        scheduler,
        completed_session,
        _row_complete(
            summary="persisted on backend",
            diagnostics=_diagnostics(turn=turn_number, player_id=completed_player_id),
        ),
        persistence=persistence,
    )

    replacement = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        persistence=persistence,
        scheduler=scheduler,
    )
    assert next(replacement) == {"type": "globalPause", "paused": False}
    replacement.close()

    assert persistence.get_row(628580, 1, turn_number, completed_player_id) is not None
    # Reconnect detach drops stream ownership without cancelling solve tokens.
    assert not in_flight_session.cancel_token.is_cancelled()
    assert in_flight_session.run_id not in scheduler._runs
    assert not scheduler.owns_table_stream(first_token)


def test_progress_without_terminal_complete_when_scope_deactivates_mid_row(sample_turn):
    """A row can emit progress on the stream and still never deliver terminal diagnostics."""
    row = _scheduled_row(sample_turn, player_id=sample_turn.scores[1].ownerid)
    row.session.event_queue.put(
        TierProgress(policy_step_id="early_game_bands", combo_count=2142, held_count=0)
    )
    row.session.event_queue.put(
        _row_complete(
            summary="terminal queued but not delivered",
            diagnostics=_diagnostics(
                turn=sample_turn.settings.turn,
                player_id=row.player_id,
            ),
        )
    )

    scope_active = True
    stream = iter_multiplexed_inference_events(
        (row,),
        tag_player_id=True,
        is_stream_active=lambda: scope_active,
    )
    progress = next(stream)
    assert progress["type"] == "progress"
    assert progress["playerId"] == row.player_id
    assert progress.get("policyStepId") == "early_game_bands"
    assert "diagnostics" not in progress

    scope_active = False
    assert list(stream) == []


def test_stream_disconnect_leaves_in_flight_row_without_persisted_terminal_state(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Disconnect before terminal: in-flight row is cancelled without persistence."""
    persistence = InferenceRowPersistenceService(memory_backend)
    scheduler = _install_workerless_scheduler(
        monkeypatch,
        on_row_complete=persistence.persist_row_complete,
    )
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    turn_number = sample_turn.settings.turn
    target_player_id = player_ids[1]

    first_stream = iter_scores_table_inference_events(
        sample_turn,
        player_ids,
        game_id=628580,
        perspective=1,
        persistence=persistence,
        scheduler=scheduler,
    )
    next(first_stream)

    collected: list[dict[str, object]] = []

    def consume_first_stream() -> None:
        collected.extend(_collect_stream_events(first_stream))

    thread = threading.Thread(target=consume_first_stream, daemon=True)
    thread.start()
    _wait_until(lambda: len(scheduler._runs) == len(player_ids))

    controller = controller_for_scope(
        InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=turn_number,
        )
    )
    assert controller is not None
    controller.end_stream(scheduler)
    thread.join(timeout=2.0)

    assert persistence.get_row(628580, 1, turn_number, target_player_id) is None
    target_completes = [
        event
        for event in collected
        if event.get("type") == "complete" and event.get("playerId") == target_player_id
    ]
    assert target_completes == []


def test_open_stream_scope_keeps_multiplex_alive_after_all_rows_terminal(sample_turn):
    """Documents: an active scope prevents stream exit even after every row has completed."""
    row = _scheduled_row(sample_turn, player_id=sample_turn.scores[0].ownerid)
    row.session.event_queue.put(_row_complete(summary="done"))

    stream = iter_multiplexed_inference_events(
        (row,),
        tag_player_id=True,
        is_stream_active=lambda: True,
    )
    terminal = next(stream)
    assert terminal["type"] == "complete"

    blocked = threading.Event()

    def read_next() -> None:
        try:
            next(stream)
        finally:
            blocked.set()

    reader = threading.Thread(target=read_next, daemon=True)
    reader.start()
    reader.join(timeout=0.2)
    assert not blocked.is_set()


def test_late_complete_on_queue_after_scope_deactivation_is_not_yielded(sample_turn):
    """Terminal events arriving after scope deactivation never reach the consumer."""
    row = _scheduled_row(sample_turn, player_id=sample_turn.scores[0].ownerid)
    scope_active = True

    stream = iter_multiplexed_inference_events(
        (row,),
        tag_player_id=True,
        is_stream_active=lambda: scope_active,
    )

    scope_active = False
    assert list(stream) == []

    row.session.event_queue.put(
        _row_complete(
            summary="too late",
            diagnostics=_diagnostics(turn=sample_turn.settings.turn, player_id=row.player_id),
        )
    )

    assert list(stream) == []


def test_persisted_row_replays_on_new_stream_without_scheduler_work(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Reconnect path serves cached terminal state when persistence already holds the row."""
    persistence = InferenceRowPersistenceService(memory_backend)
    scheduler = _install_workerless_scheduler(
        monkeypatch,
        on_row_complete=persistence.persist_row_complete,
    )
    player_id = sample_turn.scores[0].ownerid
    turn_number = sample_turn.settings.turn

    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=turn_number)
    stream_token = scheduler.begin_scope(scope)
    scheduled = schedule_inference_row(
        scheduler,
        score=sample_turn.scores[0],
        turn=sample_turn,
        player_id=player_id,
        game_id=628580,
        perspective=1,
        stream_token=stream_token,
    )
    assert scheduled is not None
    _complete_row_via_scheduler(
        scheduler,
        scheduled.session,
        _row_complete(
            summary="terminal before reconnect",
            diagnostics=_diagnostics(turn=turn_number, player_id=player_id),
        ),
        persistence=persistence,
    )
    scheduler.end_inference_stream(scope, (scheduled.session,), stream_token=stream_token)

    replay = iter_scores_table_inference_events(
        sample_turn,
        (player_id,),
        game_id=628580,
        perspective=1,
        persistence=persistence,
        scheduler=scheduler,
    )
    events = [next(replay), next(replay)]
    replay.close()

    assert events[1]["type"] == "complete"
    assert events[1]["summary"] == "terminal before reconnect"
    assert events[1]["solutionCount"] == 1
    # Durable rows omit solver diagnostics (action catalogs); replay is solutions-only.
    assert events[1].get("diagnostics") is None


def test_open_stream_receives_complete_after_persist_when_scheduled_rows_empty(
    sample_turn,
    monkeypatch,
    memory_backend,
):
    """Regression: durable exact must still NDJSON-complete an open scores stream.

    Game 628580 p11 t8 pl3: DAG + persist finished while the client stayed on
    ``globalPause`` / in-progress. Multiplex can be open with empty
    ``scheduled_rows`` (missed adopt / unbind), so ``RowComplete`` on the session
    queue is never drained. Persist + node-complete must still deliver a terminal
    wire event via pending wire events (or re-bind) to the open stream.
    """
    reset_inference_table_stream_registry_for_tests()
    persistence = InferenceRowPersistenceService(memory_backend)
    scheduler = _install_workerless_scheduler(
        monkeypatch,
        on_row_complete=persistence.persist_row_complete,
    )
    player_id = sample_turn.scores[0].ownerid
    turn_number = sample_turn.settings.turn
    scope = InferenceStreamScope(game_id=628580, perspective=1, turn_number=turn_number)

    stream = iter_scores_table_inference_events(
        sample_turn,
        (player_id,),
        game_id=628580,
        perspective=1,
        persistence=persistence,
        scheduler=scheduler,
    )
    events: list[dict[str, object]] = []
    preamble_seen = threading.Event()
    terminal_seen = threading.Event()

    def consume() -> None:
        try:
            for event in stream:
                events.append(event)
                if event.get("type") == "globalPause":
                    preamble_seen.set()
                if (
                    event.get("type") in {"complete", "error"}
                    and event.get("playerId") == player_id
                ):
                    terminal_seen.set()
                    break
        finally:
            stream.close()

    reader = threading.Thread(target=consume, name="scores-stream-reader", daemon=True)
    reader.start()
    assert preamble_seen.wait(timeout=2.0), "stream never emitted preamble"

    _wait_until(lambda: len(scheduler._runs) >= 1)
    controller = controller_for_scope(scope)
    assert controller is not None
    _wait_until(lambda: player_id in controller.scheduled_rows)

    run_id = next(iter(scheduler._runs))
    row_run = scheduler._adapter_row_run(run_id)
    assert row_run is not None
    session = row_run.session

    # Unbind after multiplex is live; wake so pending_run_ids refreshes empty and
    # the loop no longer holds a stale row reference from the prior drain cycle.
    with controller.stream_lock:
        controller.scheduled_rows.clear()
    controller.wake_multiplex.set()
    time.sleep(0.15)
    assert controller.current_scheduled_rows() == ()
    assert not terminal_seen.is_set()
    assert events == [{"type": "globalPause", "paused": False}]

    row_complete = _row_complete(
        summary="persisted while multiplex unbound",
        diagnostics=_diagnostics(turn=turn_number, player_id=player_id),
    )
    persistence.persist_row_complete(session, row_complete)
    assert persistence.get_row(628580, 1, turn_number, player_id) is not None

    compute_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=turn_number,
        player_id=player_id,
    )
    node = ComputeNodeRun(
        scope=compute_scope,
        dependency_scopes=(),
        state="complete",
        result_wire={"runId": run_id, "rowComplete": row_complete},
    )
    scheduler._on_orchestrator_node_complete(compute_scope, node)

    assert terminal_seen.wait(timeout=2.0), (
        f"open stream never received terminal event after persist+node-complete (events={events!r})"
    )
    reader.join(timeout=2.0)
    completes = [
        event
        for event in events
        if event.get("type") == "complete" and event.get("playerId") == player_id
    ]
    assert completes, f"expected complete for player {player_id}, got {events!r}"
    assert completes[-1].get("summary") == "persisted while multiplex unbound"
    assert persistence.get_row(628580, 1, turn_number, player_id) is not None

    reset_inference_table_stream_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
