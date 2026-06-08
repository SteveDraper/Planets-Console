"""NDJSON event generator for one scoreboard row inference stream."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from api.analytics.military_score_inference.inference_scheduler import get_inference_row_scheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    cleanup_inference_stream_sessions,
    immediate_row_inference_events,
    schedule_inference_row,
    session_domain_event_to_wire_events,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.models.game import TurnInfo


def iter_scores_row_inference_events(
    turn: TurnInfo,
    player_id: int,
    *,
    game_id: int,
    perspective: int,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
) -> Iterator[dict[str, object]]:
    """Yield inference stream wire events for one scoreboard row."""
    immediate = immediate_row_inference_events(
        turn,
        player_id,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if immediate is not None:
        yield from immediate
        return

    score = next(row for row in turn.scores if row.ownerid == player_id)
    turn_number = turn.settings.turn
    stream_scope = InferenceStreamScope(
        game_id=game_id,
        perspective=perspective,
        turn_number=turn_number,
    )
    scheduler = get_inference_row_scheduler()
    scheduler.begin_scope(stream_scope)

    scheduled = schedule_inference_row(
        scheduler,
        score=score,
        turn=turn,
        player_id=player_id,
        game_id=game_id,
        perspective=perspective,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    session = scheduled.session
    try:
        while True:
            domain_event = session.event_queue.get()
            for event in session_domain_event_to_wire_events(session, domain_event):
                yield event
                if event.get("type") in ("complete", "error"):
                    return
    finally:
        cleanup_inference_stream_sessions(scheduler, (session,))
