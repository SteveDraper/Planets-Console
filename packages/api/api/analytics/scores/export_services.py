"""Per-analytic export service bundles for scores."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from api.analytics.export_context import AnalyticQueryContext, export_service_for
from api.analytics.military_score_inference.hull_catalog_mask import (
    ResolvedHullCatalogMask,
    resolve_hull_catalog_mask,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    get_inference_row_scheduler,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
)
from api.analytics.scores_assets import ANALYTIC_ID
from api.models.game import TurnInfo
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


def _default_hull_catalog_mask_resolver(
    turn: TurnInfo, player_id: int
) -> ResolvedHullCatalogMask | None:
    return resolve_hull_catalog_mask(turn, player_id, user_enabled_hull_ids=None)


def _default_stream_token_resolver(scope: InferenceStreamScope) -> str | None:
    controller = controller_for_scope(scope)
    return controller.stream_token if controller is not None else None


@dataclass(frozen=True)
class ScoresExportContext:
    """Inference services used by scores export ensure and materialization."""

    scheduler: InferenceRowScheduler = field(default_factory=get_inference_row_scheduler)
    resolve_hull_catalog_mask: Callable[[TurnInfo, int], ResolvedHullCatalogMask | None] = field(
        default_factory=lambda: _default_hull_catalog_mask_resolver
    )
    resolve_stream_token: Callable[[InferenceStreamScope], str | None] = field(
        default_factory=lambda: _default_stream_token_resolver
    )
    persistence: InferenceRowPersistenceService | None = None


def resolve_scores_services(ctx: AnalyticQueryContext) -> ScoresExportContext:
    services = export_service_for(ctx, ANALYTIC_ID, ScoresExportContext)
    return services or ScoresExportContext()
