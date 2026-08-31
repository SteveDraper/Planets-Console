"""Leaf entry points for scores military-score inference (no export catalog imports)."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.fleet.types import FleetShipRecord
from api.analytics.military_score_inference.analytic import (
    infer_military_score_build,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.fleet_torp_overlay import FleetTorpOverlay
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_admission import (
    admission_skip_api_payload,
    build_inference_unavailable_api_payload,
    is_build_inference_available,
    resolve_inference_admission_skip,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    FleetTorpInputStatus,
)
from api.models.game import TurnInfo


def get_scores_row_inference(
    turn: TurnInfo,
    player_id: int,
    *,
    perspective: int | None = None,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
    resolved_mask: ResolvedHullCatalogMask | None = None,
    fleet_torp_overlay: FleetTorpOverlay | None = None,
    fleet_torp_input_status: FleetTorpInputStatus | None = None,
    prior_fleet_max_tech_by_axis: dict[str, int] | None = None,
    prior_fleet_records: tuple[FleetShipRecord, ...] = (),
) -> dict[str, object]:
    """Run military score build inference for one scoreboard row."""
    resolved_perspective = turn.player.id if perspective is None else perspective
    if not is_build_inference_available(turn):
        return build_inference_unavailable_api_payload(player_id)
    skip = resolve_inference_admission_skip(
        turn,
        player_id,
        perspective=resolved_perspective,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if skip is not None:
        return {"playerId": player_id, **admission_skip_api_payload(skip)}
    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        raise RuntimeError("admission skip missed missing scoreboard row")
    if load_scoreboard_turn is None:
        inference = infer_military_score_build(score, turn)
    else:
        inference, _, _ = run_inference_with_artifacts(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
            resolved_mask=resolved_mask,
            fleet_torp_overlay=fleet_torp_overlay,
            fleet_torp_input_status=fleet_torp_input_status,
            prior_fleet_max_tech_by_axis=prior_fleet_max_tech_by_axis,
            prior_fleet_records=prior_fleet_records,
        )
    return {"playerId": player_id, **inference}
