"""NDJSON event generator for one scoreboard row inference stream."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
    _inference_api_payload,
)
from api.analytics.military_score_inference.inference_path import (
    InferencePath,
    resolve_inference_path,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowStreamSession,
    get_inference_row_scheduler,
)
from api.analytics.military_score_inference.solver import STATUS_STOPPED
from api.models.game import TurnInfo
from api.transport.inference_stream import inference_complete_event


def iter_scores_row_inference_events(
    turn: TurnInfo,
    player_id: int,
    *,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
) -> Iterator[dict[str, object]]:
    """Yield inference stream wire events for one scoreboard row."""
    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        yield inference_complete_event(
            status="player_not_found",
            summary=f"No score row for player {player_id}",
            solution_count=0,
            is_complete=True,
            diagnostics={"playerId": player_id, "turn": turn.settings.turn},
        )
        return

    observation = build_inference_observation(score, turn)
    path, _segments = resolve_inference_path(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )

    if path == InferencePath.NO_PRIOR_TURN:
        from api.analytics.military_score_inference.analytic import _no_prior_turn_inference_result

        payload, _, _ = _no_prior_turn_inference_result(turn, observation)
        yield inference_complete_event(
            status=str(payload.get("status", STATUS_NO_PRIOR_TURN)),
            summary=str(payload.get("summary", "")),
            solution_count=int(payload.get("solutionCount", 0)),
            is_complete=bool(payload.get("isComplete", True)),
            diagnostics=(
                payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else None
            ),
        )
        return

    session = InferenceRowStreamSession(
        player_id=player_id,
        observation=observation,
        turn=turn,
    )
    scheduler = get_inference_row_scheduler()

    if path == InferencePath.POLICY_LADDER:
        scheduler.enqueue_tier_ladder(session)
    else:

        def run_full_row(row_session: InferenceRowStreamSession) -> dict[str, object]:
            if row_session.cancel_token.is_cancelled():
                return _inference_api_payload(
                    status=STATUS_STOPPED,
                    summary="Build inference halted",
                    solutions=(),
                    diagnostics={"stopped_reason": "cancelled"},
                )
            payload, _, _ = run_inference_with_artifacts(
                score,
                turn,
                load_scoreboard_turn=load_scoreboard_turn,
            )
            if row_session.cancel_token.is_cancelled():
                payload = {
                    **payload,
                    "status": STATUS_STOPPED,
                    "summary": "Build inference halted",
                    "isComplete": True,
                }
            return payload

        scheduler.enqueue_full_row(session, run_full_row)

    try:
        while True:
            event = session.event_queue.get()
            yield event
            if event.get("type") in ("complete", "error"):
                break
    finally:
        session.cancel_token.cancel()
        scheduler.unregister_session(session.run_id)
