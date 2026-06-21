"""Gathered inference snapshot for scores export precedence and materialization."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_stream_rows import (
    RowStreamAdmission,
    resolve_row_stream_admission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.export_services import ScoresExportContext
from api.models.game import TurnInfo
from api.serialization.inference_row_persistence import PersistedInferenceRow


@dataclass(frozen=True)
class ScoresInferenceSnapshot:
    """Gathered inference state for scores export persistence and materialization."""

    persisted_row: PersistedInferenceRow | None
    admission: RowStreamAdmission | None
    scheduler_run: RowRun | None
    globally_paused: bool


def scores_inference_stream_scope(scope: ExportScope) -> InferenceStreamScope:
    return InferenceStreamScope(
        game_id=scope.game_id,
        perspective=scope.perspective,
        turn_number=scope.turn,
    )


def _load_persisted_row(
    services: ScoresExportContext,
    scope: ExportScope,
) -> PersistedInferenceRow | None:
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
    turn: TurnInfo,
) -> RowStreamAdmission | None:
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


def _scheduler_row_run(
    services: ScoresExportContext,
    scope: ExportScope,
) -> RowRun | None:
    if scope.player_id is None:
        return None
    stream_scope = scores_inference_stream_scope(scope)
    return services.scheduler.row_run_for_player(stream_scope, scope.player_id)


def gather_scores_inference_snapshot(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo | None,
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
