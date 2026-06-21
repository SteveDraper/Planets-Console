"""Shared materialization helpers for scores analytic exports."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_stream_rows import (
    resolve_row_stream_admission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores.export_precedence import (
    PERSISTABLE_INFERENCE_STATUSES,
    ScoresInferenceSnapshot,
    SearchStatus,
)
from api.analytics.scores.export_services import ScoresExportContext

__all__ = [
    "ScoresInferenceSnapshot",
    "export_meta_branch",
    "gather_scores_inference_snapshot",
    "hull_catalog_mask_branch",
    "is_persistable_inference_status",
    "scores_inference_stream_scope",
]


def export_meta_branch(
    *,
    search_status: SearchStatus,
    host_turn: int,
    solutions_held: int = 0,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "searchStatus": search_status,
        "hostTurn": host_turn,
    }
    if solutions_held > 0:
        meta["solutionsHeld"] = solutions_held
    return meta


def hull_catalog_mask_branch(enabled_hull_ids: frozenset[int] | set[int]) -> dict[str, object]:
    return {"enabledHullIds": sorted(enabled_hull_ids)}


def is_persistable_inference_status(status: str) -> bool:
    return status in PERSISTABLE_INFERENCE_STATUSES


def scores_inference_stream_scope(scope: ExportScope) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
    )


def _load_persisted_row(
    services: ScoresExportContext,
    scope: ExportScope,
):
    if services.persistence is None or scope.player_id is None:
        return None
    return services.persistence.get_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        scope.player_id,
    )


def _row_admission(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn,
):
    if scope.player_id is None:
        return None
    return resolve_row_stream_admission(
        turn,
        scope.player_id,
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
        load_scoreboard_turn=ctx.load_turn,
        persistence=services.persistence,
    )


def _scheduler_row_run(services: ScoresExportContext, scope: ExportScope):
    if scope.player_id is None:
        return None
    stream_scope = scores_inference_stream_scope(scope)
    return services.scheduler.row_run_for_player(stream_scope, scope.player_id)


def gather_scores_inference_snapshot(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn,
) -> ScoresInferenceSnapshot:
    persisted_row = _load_persisted_row(services, scope)
    if turn is None:
        return ScoresInferenceSnapshot(
            persisted_row=persisted_row,
            admission=None,
            scheduler_run=None,
            globally_paused=False,
        )

    stream_scope = scores_inference_stream_scope(scope)
    pause_status = services.scheduler.global_pause_status(stream_scope)
    return ScoresInferenceSnapshot(
        persisted_row=persisted_row,
        admission=_row_admission(ctx, services, scope, turn),
        scheduler_run=_scheduler_row_run(services, scope),
        globally_paused=bool(pause_status.get("paused")),
    )
