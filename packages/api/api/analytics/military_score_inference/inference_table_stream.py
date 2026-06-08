"""NDJSON event generator for the full scoreboard inference table stream."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_scheduler import get_inference_row_scheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    cleanup_inference_stream_sessions,
    drain_available_multiplex_events,
    immediate_row_inference_events,
    iter_multiplexed_inference_events,
    schedule_inference_row,
    tag_inference_stream_event,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.models.game import TurnInfo


def iter_scores_table_inference_events(
    turn: TurnInfo,
    player_ids: tuple[int, ...],
    *,
    game_id: int,
    perspective: int,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    resolve_mask_for_player: Callable[[int], ResolvedHullCatalogMask | None] | None = None,
) -> Iterator[dict[str, object]]:
    """Yield tagged inference events for all scoreboard rows on one NDJSON stream."""
    turn_number = turn.settings.turn
    stream_scope = InferenceStreamScope(
        game_id=game_id,
        perspective=perspective,
        turn_number=turn_number,
    )
    scheduler = get_inference_row_scheduler()
    scheduler.begin_scope(stream_scope)

    scheduled_rows: list[ScheduledInferenceRow] = []
    finished_run_ids: set[str] = set()
    for player_id in player_ids:
        immediate = immediate_row_inference_events(
            turn,
            player_id,
            load_scoreboard_turn=load_scoreboard_turn,
        )
        if immediate is not None:
            for event in immediate:
                yield tag_inference_stream_event(event, player_id=player_id)
            continue

        score = next(row for row in turn.scores if row.ownerid == player_id)
        resolved_mask = (
            resolve_mask_for_player(player_id) if resolve_mask_for_player is not None else None
        )
        scheduled_rows.append(
            schedule_inference_row(
                scheduler,
                score=score,
                turn=turn,
                player_id=player_id,
                game_id=game_id,
                perspective=perspective,
                load_scoreboard_turn=load_scoreboard_turn,
                resolved_mask=resolved_mask,
            )
        )
        yield from drain_available_multiplex_events(
            tuple(scheduled_rows),
            tag_player_id=True,
            finished_run_ids=finished_run_ids,
        )

    sessions = tuple(scheduled_rows)
    try:
        yield from iter_multiplexed_inference_events(
            sessions,
            tag_player_id=True,
            finished_run_ids=finished_run_ids,
        )
    finally:
        cleanup_inference_stream_sessions(
            scheduler,
            tuple(row.session for row in sessions),
        )


def stop_scores_table_inference_row(
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
    player_id: int,
) -> bool:
    scope = InferenceStreamScope(
        game_id=game_id,
        perspective=perspective,
        turn_number=turn_number,
    )
    return get_inference_row_scheduler().cancel_player(scope, player_id)
