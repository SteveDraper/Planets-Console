"""Prior-turn inference persistence for scores exports."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.scores.export_materialization import is_persistable_inference_status
from api.analytics.scores.export_services import ResolvedScoresServices
from api.serialization.inference_row_persistence import persisted_inference_row_from_wire_complete
from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete


def persist_prior_turn_inference_if_persistable(
    ctx: AnalyticQueryContext,
    services: ResolvedScoresServices,
    scope: ExportScope,
    turn,
) -> None:
    from api.analytics.scores import get_scores_row_inference

    player_id = scope.player_id
    assert player_id is not None
    resolved_mask = services.resolve_hull_catalog_mask(turn, player_id)
    inference = get_scores_row_inference(
        turn,
        player_id,
        load_scoreboard_turn=ctx.load_turn,
        resolved_mask=resolved_mask,
    )
    if services.persistence is None:
        return
    status = str(inference.get("status", ""))
    if not is_persistable_inference_status(status):
        return
    wire_event = inference_api_payload_to_wire_complete(inference)
    row = persisted_inference_row_from_wire_complete(wire_event)
    services.persistence.put_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        player_id,
        row,
    )
