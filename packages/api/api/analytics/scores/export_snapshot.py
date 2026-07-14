"""Gathered inference snapshot for scores export precedence and materialization."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ImmediateRowAdmission,
    RowStreamAdmission,
    resolve_row_stream_admission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.export_wire import terminal_row_admission
from api.analytics.scores_assets import ANALYTIC_ID
from api.models.game import TurnInfo
from api.serialization.inference_row_persistence import PersistedInferenceRow


@dataclass(frozen=True)
class ScoresInferenceSnapshot:
    """Gathered inference state for scores export persistence and materialization."""

    persisted_row: PersistedInferenceRow | None
    stream_admission: RowStreamAdmission | None
    ensure_sync_admission: ImmediateRowAdmission | None
    scheduler_run: RowRun | None
    globally_paused: bool

    def resolved_terminal_admission(
        self,
    ) -> ImmediateRowAdmission | CachedCompleteRowAdmission | None:
        """Terminal row admission for precedence: ensure-sync overrides live stream."""
        if self.ensure_sync_admission is not None:
            return self.ensure_sync_admission
        return terminal_row_admission(self.stream_admission)


def _ensure_sync_admission_from_context(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> ImmediateRowAdmission | None:
    stored = ctx.ensure_ephemeral(ANALYTIC_ID, scope)
    if stored is None:
        return None
    if not isinstance(stored, ImmediateRowAdmission):
        raise TypeError(
            f"scores ensure ephemeral must be ImmediateRowAdmission, got {type(stored).__name__}"
        )
    return stored


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


def _cached_stream_admission(
    services: ScoresExportContext,
    scope: ExportScope,
) -> CachedCompleteRowAdmission | None:
    """Return persisted wire-complete admission only; never run row inference."""
    if services.persistence is None or scope.player_id is None:
        return None
    cached = services.persistence.wire_complete_for_row(
        scope.game_id,
        scope.perspective,
        scope.turn,
        scope.player_id,
    )
    if cached is None:
        return None
    return CachedCompleteRowAdmission(event=cached)


def _gather_scores_probe_snapshot(
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo | None,
    *,
    ensure_sync_admission: ImmediateRowAdmission | None,
) -> ScoresInferenceSnapshot:
    """Shared probe gather: cached stream admission only, no live inference."""
    persisted_row = _load_persisted_row(services, scope)
    if turn is None:
        return ScoresInferenceSnapshot(
            persisted_row=persisted_row,
            stream_admission=None,
            ensure_sync_admission=ensure_sync_admission,
            scheduler_run=None,
            globally_paused=False,
        )

    stream_scope = scores_inference_stream_scope(scope)
    pause_status = services.scheduler.global_pause_status(stream_scope)
    return ScoresInferenceSnapshot(
        persisted_row=persisted_row,
        stream_admission=_cached_stream_admission(services, scope),
        ensure_sync_admission=ensure_sync_admission,
        scheduler_run=_scheduler_row_run(services, scope),
        globally_paused=bool(pause_status.get("paused")),
    )


def gather_scores_materialization_probe_snapshot(
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo,
) -> ScoresInferenceSnapshot:
    """Lightweight scores snapshot for fleet materialization provenance (no export context)."""
    return _gather_scores_probe_snapshot(
        services,
        scope,
        turn,
        ensure_sync_admission=None,
    )


def gather_scores_ensure_probe_snapshot(
    ctx: AnalyticQueryContext,
    services: ScoresExportContext,
    scope: ExportScope,
    turn: TurnInfo | None,
) -> ScoresInferenceSnapshot:
    """Lightweight snapshot for export probe walks: persistence and scheduler lookups only."""
    return _gather_scores_probe_snapshot(
        services,
        scope,
        turn,
        ensure_sync_admission=_ensure_sync_admission_from_context(ctx, scope),
    )


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
            stream_admission=None,
            ensure_sync_admission=None,
            scheduler_run=None,
            globally_paused=False,
        )

    stream_scope = scores_inference_stream_scope(scope)
    pause_status = services.scheduler.global_pause_status(stream_scope)
    ensure_sync_admission = _ensure_sync_admission_from_context(ctx, scope)
    # Ensure-ephemeral terminals already own precedence; skip live stream admission
    # so cheap-path helpers (immediate_row_inference_events) are not re-run.
    stream_admission = (
        None if ensure_sync_admission is not None else _row_admission(ctx, services, scope, turn)
    )
    return ScoresInferenceSnapshot(
        persisted_row=persisted_row,
        stream_admission=stream_admission,
        ensure_sync_admission=ensure_sync_admission,
        scheduler_run=_scheduler_row_run(services, scope),
        globally_paused=bool(pause_status.get("paused")),
    )
