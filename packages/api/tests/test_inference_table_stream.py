"""Tests for the multiplexed scoreboard inference table stream."""

from __future__ import annotations

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    _TierJob,
    get_inference_row_scheduler,
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
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.solver import STATUS_EXACT


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


def test_table_stream_emits_global_pause_snapshot_when_scope_is_paused(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = get_inference_row_scheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)

    events = list(
        iter_scores_table_inference_events(
            sample_turn,
            (),
            game_id=628580,
            perspective=1,
        )
    )
    assert events[0] == {"type": "globalPause", "paused": True}


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
    scheduler.register_session(session)
    scheduler.register_session(other_session)
    scheduler._enqueue_job(_TierJob(session=session))
    scheduler._enqueue_continuation(session)
    scheduler._enqueue_job(_TierJob(session=other_session))

    scheduler.cancel_run(session.run_id)

    assert session.cancel_token.is_cancelled() is True
    assert scheduler._tier_one_queue.qsize() == 1
    remaining_job = scheduler._tier_one_queue.get_nowait()
    assert remaining_job.session.run_id == other_session.run_id
    assert session.run_id not in scheduler._continuation_by_run
