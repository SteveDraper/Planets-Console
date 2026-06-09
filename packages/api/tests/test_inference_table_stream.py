"""Tests for the multiplexed scoreboard inference table stream."""

from __future__ import annotations

import json

import pytest
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    drain_available_multiplex_events,
    iter_multiplexed_inference_events,
    iter_scores_table_inference_events,
    tag_inference_stream_event,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.errors import ConflictError
from api.transport.inference_stream import stream_inference_ndjson


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


def _wire_complete_event(*, summary: str) -> dict[str, object]:
    return {
        "type": "complete",
        "status": STATUS_EXACT,
        "summary": summary,
        "solutionCount": 1,
        "isComplete": True,
    }


def test_table_stream_emits_global_pause_snapshot_on_connect(sample_turn):
    reset_inference_row_scheduler_for_tests()
    events = list(
        iter_scores_table_inference_events(
            sample_turn,
            (),
            game_id=628580,
            perspective=1,
        )
    )
    assert events[0] == {"type": "globalPause", "paused": False}


def test_table_stream_rejects_duplicate_concurrent_connection(sample_turn):
    reset_inference_row_scheduler_for_tests()
    active_stream = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
    )
    assert next(active_stream) == {"type": "globalPause", "paused": False}

    with pytest.raises(ConflictError, match="already active for this scope"):
        list(
            iter_scores_table_inference_events(
                sample_turn,
                (),
                game_id=628580,
                perspective=1,
            )
        )

    active_stream.close()


def test_table_stream_duplicate_connection_surfaces_error_event(sample_turn):
    reset_inference_row_scheduler_for_tests()
    active_stream = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
    )
    next(active_stream)

    def duplicate_loader():
        yield from iter_scores_table_inference_events(
            sample_turn,
            (),
            game_id=628580,
            perspective=1,
        )

    lines = list(stream_inference_ndjson(duplicate_loader))
    active_stream.close()

    assert len(lines) == 1
    error = json.loads(lines[0])
    assert error == {
        "type": "error",
        "detail": "An inference table stream is already active for this scope.",
    }


def test_tag_inference_stream_event_adds_player_id_except_global_pause():
    tagged = tag_inference_stream_event(
        _wire_complete_event(summary="done"),
        player_id=3,
    )
    assert tagged["playerId"] == 3
    assert tag_inference_stream_event({"type": "globalPause", "paused": True}, player_id=3) == {
        "type": "globalPause",
        "paused": True,
    }


def test_drain_available_multiplex_events_returns_queued_events_without_blocking(sample_turn):
    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    rows = []
    for player_id in player_ids:
        session = _session_for_player(sample_turn, player_id=player_id)
        session.event_queue.put(
            RowComplete(
                result=InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
                summary_override=f"Player {player_id} ok",
            )
        )
        rows.append(ScheduledInferenceRow(player_id=player_id, session=session))

    finished: set[str] = set()
    events = list(
        drain_available_multiplex_events(
            (rows[0],),
            tag_player_id=True,
            finished_run_ids=finished,
        )
    )
    assert len(events) == 1
    assert events[0]["playerId"] == player_ids[0]


def test_multiplexed_events_include_player_id_tags(sample_turn):
    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    rows = []
    for player_id in player_ids:
        session = _session_for_player(sample_turn, player_id=player_id)
        session.event_queue.put(
            RowComplete(
                result=InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
                summary_override=f"Player {player_id} ok",
            )
        )
        rows.append(ScheduledInferenceRow(player_id=player_id, session=session))

    events = list(iter_multiplexed_inference_events(tuple(rows), tag_player_id=True))
    complete_player_ids = {
        event["playerId"]
        for event in events
        if event.get("type") == "complete" and isinstance(event.get("playerId"), int)
    }
    assert complete_player_ids == set(player_ids)


def test_cancel_run_purges_queued_tier_jobs_for_run(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    session = _session_for_player(sample_turn, player_id=sample_turn.scores[0].ownerid)
    other_session = _session_for_player(sample_turn, player_id=sample_turn.scores[1].ownerid)
    scheduler.enqueue_tier_ladder(session)
    scheduler.enqueue_tier_ladder(other_session)
    scheduler._enqueue_continuation(session)

    scheduler.cancel_run(session.run_id)

    assert session.cancel_token.is_cancelled() is True
    assert scheduler._pending_tier_jobs.qsize() == 1
    remaining_job = scheduler._pending_tier_jobs.get_nowait()
    assert remaining_job.session.run_id == other_session.run_id
    cancelled_run = scheduler._runs.get(session.run_id)
    assert cancelled_run is None or not cancelled_run.continuation_jobs
