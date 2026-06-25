"""Load scores held solutions for fleet inference ingest."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.export_context import make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    get_inference_row_scheduler,
)
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.scores.export_precedence import SearchStatus, resolve_scores_export
from api.analytics.scores.export_services import ScoresExportContext
from api.analytics.scores.export_snapshot import gather_scores_ensure_probe_snapshot
from api.models.game import TurnInfo
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


@dataclass(frozen=True)
class FleetHeldInference:
    """Resolved scores held solutions for one player on one host turn."""

    search_status: SearchStatus
    solutions: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class FleetInferenceSupport:
    """Read-only scores inference access for fleet materialization."""

    persistence: InferenceRowPersistenceService | None = None
    scheduler: InferenceRowScheduler | None = None

    def held_inference_for_player(
        self,
        *,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
        turn: TurnInfo,
        load_turn,
    ) -> FleetHeldInference:
        if self.persistence is None:
            return FleetHeldInference(search_status="not_started", solutions=())

        scheduler = self.scheduler if self.scheduler is not None else get_inference_row_scheduler()
        scores_services = ScoresExportContext(
            persistence=self.persistence,
            scheduler=scheduler,
        )
        ctx = make_analytic_query_context(
            turn,
            TurnAnalyticsOptions(),
            load_turn=load_turn,
            export_services={"scores": scores_services},
        )
        scope = ExportScope(
            game_id=game_id,
            perspective=perspective,
            turn=host_turn,
            player_id=player_id,
        )
        snapshot = gather_scores_ensure_probe_snapshot(ctx, scores_services, scope, turn)
        resolved = resolve_scores_export(snapshot)
        return FleetHeldInference(
            search_status=resolved.decision.search_status,
            solutions=tuple(resolved.payload.solutions),
        )
