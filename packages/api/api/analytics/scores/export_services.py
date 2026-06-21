"""Per-analytic export service bundles for scores."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.military_score_inference.hull_catalog_mask import resolve_hull_catalog_mask
from api.analytics.military_score_inference.inference_scheduler import get_inference_row_scheduler
from api.analytics.scores_assets import ANALYTIC_ID

if TYPE_CHECKING:
    from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
    from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
    from api.models.game import TurnInfo
    from api.services.inference_row_persistence_service import InferenceRowPersistenceService


@dataclass(frozen=True)
class ScoresExportContext:
    """Inference services used by scores export ensure and materialization."""

    persistence: InferenceRowPersistenceService | None = None
    scheduler: InferenceRowScheduler | None = None
    resolve_hull_catalog_mask: Callable[[TurnInfo, int], ResolvedHullCatalogMask | None] | None = (
        None
    )


@dataclass(frozen=True)
class ResolvedScoresServices:
    """Scores export services with scheduler and mask fallbacks applied."""

    persistence: InferenceRowPersistenceService | None
    scheduler: InferenceRowScheduler
    _resolve_hull_catalog_mask: Callable[[TurnInfo, int], ResolvedHullCatalogMask | None] | None

    def resolve_hull_catalog_mask(
        self, turn: TurnInfo, player_id: int
    ) -> ResolvedHullCatalogMask | None:
        if self._resolve_hull_catalog_mask is not None:
            return self._resolve_hull_catalog_mask(turn, player_id)
        return resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=None)


def resolve_scores_services(ctx: AnalyticQueryContext) -> ResolvedScoresServices:
    services = export_service_for(ctx, ANALYTIC_ID, ScoresExportContext)
    if services is None:
        return ResolvedScoresServices(
            persistence=None,
            scheduler=get_inference_row_scheduler(),
            _resolve_hull_catalog_mask=None,
        )
    return ResolvedScoresServices(
        persistence=services.persistence,
        scheduler=services.scheduler or get_inference_row_scheduler(),
        _resolve_hull_catalog_mask=services.resolve_hull_catalog_mask,
    )
