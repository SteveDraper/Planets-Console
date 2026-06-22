"""Leaf entry points for scores military-score inference (no export catalog imports)."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.military_score_inference.analytic import (
    infer_military_score_build,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_api_payload import STATUS_PLAYER_NOT_FOUND
from api.models.game import TurnInfo


def get_scores_row_inference(
    turn: TurnInfo,
    player_id: int,
    *,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    resolved_mask: ResolvedHullCatalogMask | None = None,
) -> dict[str, object]:
    """Run military score build inference for one scoreboard row."""
    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        return {
            "playerId": player_id,
            "status": STATUS_PLAYER_NOT_FOUND,
            "summary": f"No score row for player {player_id}",
            "solutionCount": 0,
            "isComplete": True,
            "solutions": [],
            "diagnostics": {"playerId": player_id, "turn": turn.settings.turn},
        }
    if load_scoreboard_turn is None:
        inference = infer_military_score_build(score, turn)
    else:
        inference, _, _ = run_inference_with_artifacts(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
            resolved_mask=resolved_mask,
        )
    return {"playerId": player_id, **inference}
