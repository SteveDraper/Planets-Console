"""Tests for the multiplexed scoreboard inference table stream."""

from __future__ import annotations

import json

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    drain_available_multiplex_events,
    iter_multiplexed_inference_events,
    iter_scores_table_inference_events,
    schedule_inference_row,
    tag_inference_stream_event,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.scope import ComputeScope
from api.transport.inference_stream import (
    stream_inference_ndjson,
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
    stream = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
    )
    assert next(stream) == {"type": "globalPause", "paused": False}
    stream.close()


def test_table_stream_reconnect_preempts_active_scope(sample_turn):
    reset_inference_row_scheduler_for_tests()
    active_stream = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
    )
    assert next(active_stream) == {"type": "globalPause", "paused": False}

    replacement = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
    )
    assert next(replacement) == {"type": "globalPause", "paused": False}

    active_stream.close()
    replacement.close()


def test_table_stream_reconnect_via_ndjson_transport(sample_turn):
    reset_inference_row_scheduler_for_tests()
    active_stream = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
    )
    next(active_stream)

    def replacement_loader():
        yield from iter_scores_table_inference_events(
            sample_turn,
            (),
            game_id=628580,
            perspective=1,
        )

    lines = list(stream_inference_ndjson(replacement_loader))
    active_stream.close()

    assert len(lines) >= 1
    assert json.loads(lines[0]) == {"type": "globalPause", "paused": False}


def test_schedule_inference_row_ignores_stale_stream_token_after_scope_end(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    score = sample_turn.scores[0]
    first_token = scheduler.begin_scope(scope)

    active_row = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=score.ownerid,
        game_id=628580,
        perspective=1,
        stream_token=first_token,
    )
    assert active_row is not None

    scheduler.end_inference_stream(scope, (active_row.session,), stream_token=first_token)
    scheduler.begin_scope(scope)

    stale_row = schedule_inference_row(
        scheduler,
        score=score,
        turn=sample_turn,
        player_id=score.ownerid,
        game_id=628580,
        perspective=1,
        stream_token=first_token,
    )
    assert stale_row is None
    assert active_row.session.cancel_token.is_cancelled()


def test_table_stream_reconnect_preempts_in_flight_rows_for_same_scope(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    sessions = [
        _session_for_player(sample_turn, player_id=row.ownerid) for row in sample_turn.scores[:2]
    ]
    for session in sessions:
        scheduler.enqueue_tier_ladder(session, stream_token=stream_token)

    replacement = iter_scores_table_inference_events(
        sample_turn,
        (),
        game_id=628580,
        perspective=1,
        scheduler=scheduler,
    )
    assert next(replacement) == {"type": "globalPause", "paused": False}
    replacement.close()

    assert not scheduler.owns_table_stream(stream_token)
    for session in sessions:
        assert session.cancel_token.is_cancelled()


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
            row_complete_with_summary(
                InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
                summary=f"Player {player_id} ok",
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
            row_complete_with_summary(
                InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
                summary=f"Player {player_id} ok",
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


def test_cancel_run_clears_gated_orchestrator_continuation(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    session = _session_for_player(sample_turn, player_id=sample_turn.scores[0].ownerid)
    other_session = _session_for_player(sample_turn, player_id=sample_turn.scores[1].ownerid)
    scheduler.enqueue_tier_ladder(session, stream_token=stream_token)
    scheduler.enqueue_tier_ladder(other_session, stream_token=stream_token)
    scheduler.pause_globally(scope)

    session_root_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=session.game_id,
        perspective=session.perspective,
        turn=session.turn_number,
        player_id=session.player_id,
    )
    other_root_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=other_session.game_id,
        perspective=other_session.perspective,
        turn=other_session.turn_number,
        player_id=other_session.player_id,
    )
    scheduler._stream_bindings[stream_token] = type(
        "FakeBinding",
        (),
        {
            "orchestrator": type(
                "FakeOrchestrator",
                (),
                {
                    "nodes": {
                        session_root_scope: ComputeNodeRun(
                            scope=session_root_scope,
                            dependency_scopes=(),
                            state="ready",
                            step_index=1,
                            profile_step_index=1,
                        ),
                        other_root_scope: ComputeNodeRun(
                            scope=other_root_scope,
                            dependency_scopes=(),
                            state="ready",
                            step_index=0,
                            profile_step_index=1,
                        ),
                    },
                    "register_dispatch_gate": lambda _gate: (lambda: None),
                    "dispatch_ready_work": lambda: None,
                    "register_node_complete_listener": lambda _listener: lambda: None,
                },
            )(),
            "unregister_listener": lambda: None,
            "unregister_dispatch_gate": None,
            "query_context": object(),
        },
    )()

    assert scheduler.global_pause_status(scope)["heldContinuationCount"] == 1

    scheduler.cancel_run(session.run_id)

    assert session.cancel_token.is_cancelled() is True
    assert session.run_id not in scheduler._runs
    assert other_session.run_id in scheduler._runs
    status = scheduler.global_pause_status(scope)
    assert status["heldContinuationCount"] == 0
